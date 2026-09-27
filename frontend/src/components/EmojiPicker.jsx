/*
  EmojiPicker — bouton 😊 + palette d'emojis pour les zones de saisie des
  messages (lot 27) : conversation WhatsApp, envoi SMS, boîte de réception unifiée.

  - catégories (récents, visages, gestes, cœurs, travail, nourriture, nature,
    symboles, drapeaux) et recherche par mot-clé en français ;
  - l'emoji est inséré À LA POSITION DU CURSEUR dans la zone de saisie, puis
    le curseur est replacé juste après ;
  - les 24 derniers emojis utilisés sont mémorisés sur l'appareil.
  Aucune dépendance : les emojis sont des caractères Unicode standard, que
  WhatsApp et les téléphones affichent directement (en SMS, un emoji fait passer
  le message en encodage Unicode : 70 caractères par SMS au lieu de 160).

  Props :
    textareaRef  — ref React de la zone de saisie (textarea ou input)
    value        — texte actuel
    onChange     — (nouveauTexte) => void
    disabled, className, testId, maxLength (facultatif)
*/
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Smile, Search, X } from "lucide-react";

// Catégories : [clé, libellé, icône, liste « emoji mot-clé mot-clé… »]
const CATEGORIES = [
  ["smileys", "Visages", "😀", [
    "😀 sourire", "😃 sourire", "😄 rire", "😁 rire", "😆 rire", "😅 gêne", "😂 larmes rire", "🤣 rire", "😊 content", "😇 ange",
    "🙂 sourire", "🙃 inverse", "😉 clin", "😌 soulagé", "😍 amour", "🥰 amour", "😘 bisou", "😗 bisou", "😋 miam", "😛 langue",
    "😜 clin langue", "🤪 fou", "🤨 doute", "🧐 examiner", "🤓 lunettes", "😎 cool", "🤩 étoiles", "🥳 fête", "😏 malin", "😒 bof",
    "😞 déçu", "😔 triste", "😟 inquiet", "😕 confus", "🙁 triste", "😣 effort", "😖 confus", "😫 fatigué", "😩 las", "🥺 supplier",
    "😢 pleurer", "😭 pleurer", "😤 fier", "😠 colère", "😡 colère", "🤬 injure", "🤯 choc", "😳 gêne", "🥵 chaud", "🥶 froid",
    "😱 peur", "😨 peur", "😰 anxieux", "😥 déçu", "😓 sueur", "🤗 câlin", "🤔 réfléchir", "🤭 oups", "🤫 silence", "🤥 mensonge",
    "😶 muet", "😐 neutre", "😑 blasé", "😬 grimace", "🙄 yeux", "😯 surpris", "😦 surpris", "😮 bouche", "😲 étonné", "🥱 bâiller",
    "😴 dormir", "🤤 baver", "😪 sommeil", "😵 étourdi", "🤐 bouche cousue", "🥴 éméché", "🤢 nausée", "🤮 vomir", "🤧 éternuer", "😷 masque",
    "🤒 malade", "🤕 blessé", "🤑 argent", "🤠 cowboy",
  ]],
  ["gestures", "Gestes", "👍", [
    "👍 pouce oui ok", "👎 pouce non", "👌 ok", "✌️ victoire", "🤞 chance", "🤝 accord poignée", "🙏 merci prière svp", "👏 bravo applaudir",
    "🙌 hourra", "👐 mains", "🤲 mains", "👋 salut bonjour", "🤚 main", "✋ stop", "🖐️ main", "🖖 salut", "🤙 appel", "💪 force",
    "👊 poing", "✊ poing", "🤛 poing", "🤜 poing", "☝️ un", "👆 haut", "👇 bas", "👉 droite", "👈 gauche", "✍️ écrire signer",
    "🤳 selfie", "💅 ongles", "🙋 lever main", "🙆 ok", "🙅 non", "🤷 bof", "🤦 facepalm", "🙇 excuses", "💁 info",
  ]],
  ["hearts", "Cœurs", "❤️", [
    "❤️ cœur amour", "🧡 cœur", "💛 cœur", "💚 cœur", "💙 cœur", "💜 cœur", "🖤 cœur", "🤍 cœur", "🤎 cœur", "💔 cœur brisé",
    "❣️ cœur", "💕 cœurs", "💞 cœurs", "💓 cœur", "💗 cœur", "💖 cœur", "💘 flèche", "💝 cadeau", "💟 cœur", "💯 cent",
  ]],
  ["work", "Travail", "💼", [
    "💼 travail mallette", "📄 document", "📑 documents", "📋 liste", "📌 épingle", "📎 trombone", "✏️ crayon", "🖊️ stylo", "📝 note",
    "📅 calendrier date", "📆 agenda", "🗓️ planning", "⏰ réveil heure", "⏳ attente", "⌛ temps", "📞 téléphone appel", "📱 portable",
    "💻 ordinateur", "🖥️ écran", "🖨️ imprimante", "📧 email", "✉️ lettre", "📩 message", "📨 courrier", "📦 colis livraison",
    "🏢 bureau entreprise", "🏥 hôpital pharmacie", "💊 médicament", "🩺 médecin", "🧾 facture reçu", "💰 argent", "💵 billets",
    "💳 carte paiement", "🏦 banque", "📈 hausse", "📉 baisse", "📊 statistiques", "🔒 sécurisé", "🔑 clé", "🔔 rappel notification",
    "📣 annonce", "🎯 objectif", "✅ fait valide", "☑️ coché", "❌ non annulé", "⚠️ attention", "🚚 livraison camion", "🛒 achat panier",
  ]],
  ["food", "Nourriture", "🍽️", [
    "☕ café", "🍵 thé", "🥤 boisson", "🧃 jus", "🍺 bière", "🍷 vin", "🥂 santé", "🍞 pain", "🥖 baguette", "🍗 poulet", "🍖 viande",
    "🍚 riz", "🍲 plat", "🥘 plat", "🍛 curry", "🥗 salade", "🍕 pizza", "🍔 burger", "🍟 frites", "🍳 œuf", "🍌 banane", "🍊 orange",
    "🍉 pastèque", "🥭 mangue", "🍍 ananas", "🥥 coco", "🍰 gâteau", "🎂 anniversaire gâteau", "🍫 chocolat", "🍬 bonbon",
  ]],
  ["nature", "Nature", "🌍", [
    "☀️ soleil", "🌤️ beau temps", "⛅ nuage", "🌧️ pluie", "⛈️ orage", "🌈 arc-en-ciel", "🔥 feu", "💧 eau goutte", "🌊 vague",
    "🌍 afrique monde", "🌱 plante", "🌳 arbre", "🌴 palmier", "🌸 fleur", "🌹 rose", "🌻 tournesol", "🍀 chance trèfle",
    "🐶 chien", "🐱 chat", "🐔 poule", "🐄 vache", "🐐 chèvre", "🐑 mouton", "🦁 lion", "🐘 éléphant", "🦋 papillon", "⭐ étoile", "🌙 lune",
  ]],
  ["symbols", "Symboles", "✨", [
    "✨ étincelles", "🎉 fête bravo", "🎊 fête", "🎁 cadeau", "🏆 trophée", "🥇 médaille", "🎓 diplôme", "⚡ éclair", "💡 idée",
    "🔴 rouge", "🟠 orange", "🟡 jaune", "🟢 vert", "🔵 bleu", "🟣 violet", "⚫ noir", "⚪ blanc", "▶️ lecture", "⏸️ pause",
    "🔄 actualiser", "➡️ droite", "⬅️ gauche", "⬆️ haut", "⬇️ bas", "ℹ️ info", "❓ question", "❗ important", "‼️ urgent",
    "🆕 nouveau", "🆗 ok", "🆘 sos", "🔝 top", "💬 discussion", "🗨️ bulle", "👀 regarder", "🙈 oups", "🤖 robot", "🚀 lancement",
  ]],
  ["flags", "Drapeaux", "🇧🇫", [
    "🇧🇫 burkina faso", "🇨🇮 côte d'ivoire", "🇲🇱 mali", "🇳🇪 niger", "🇸🇳 sénégal", "🇹🇬 togo", "🇧🇯 bénin", "🇬🇭 ghana",
    "🇬🇳 guinée", "🇨🇲 cameroun", "🇲🇦 maroc", "🇹🇳 tunisie", "🇩🇿 algérie", "🇳🇬 nigeria", "🇫🇷 france", "🇧🇪 belgique",
    "🇨🇦 canada", "🇺🇸 usa", "🇪🇺 europe", "🏳️ blanc",
  ]],
];
const RECENT_KEY = "sawali_recent_emojis";

// Lecture / écriture des récents (stockage local de l'appareil, tolérant aux erreurs)
const readRecent = () => { try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); } catch { return []; } };
const saveRecent = (list) => { try { localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 24))); } catch { /* stockage indisponible */ } };

export default function EmojiPicker({ textareaRef, value, onChange, disabled = false, className = "", testId = "emoji", maxLength }) {
  const [open, setOpen] = useState(false);
  const [cat, setCat] = useState("smileys");
  const [query, setQuery] = useState("");
  const [recent, setRecent] = useState(readRecent);
  const boxRef = useRef(null);

  // Fermeture au clic en dehors de la palette ou avec Échap
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  // Emojis affichés : recherche sur toutes les catégories, sinon la catégorie choisie
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q) {
      return CATEGORIES.flatMap(([, , , list]) => list).filter((e) => e.toLowerCase().includes(q)).map((e) => e.split(" ")[0]);
    }
    if (cat === "recent") return recent;
    return (CATEGORIES.find(([k]) => k === cat)?.[3] || []).map((e) => e.split(" ")[0]);
  }, [cat, query, recent]);

  // Insère l'emoji à la position du curseur et replace le curseur juste après
  const insert = (emoji) => {
    const el = textareaRef?.current;
    const text = value || "";
    const start = el && typeof el.selectionStart === "number" ? el.selectionStart : text.length;
    const end = el && typeof el.selectionEnd === "number" ? el.selectionEnd : text.length;
    let next = text.slice(0, start) + emoji + text.slice(end);
    if (maxLength && next.length > maxLength) return;       // pas de dépassement de la limite
    onChange(next);
    const caret = start + emoji.length;
    requestAnimationFrame(() => {
      if (!el) return;
      el.focus();
      try { el.setSelectionRange(caret, caret); } catch { /* champ sans sélection */ }
    });
    const nextRecent = [emoji, ...recent.filter((e) => e !== emoji)].slice(0, 24);
    setRecent(nextRecent);
    saveRecent(nextRecent);
  };

  const tabs = [["recent", "Récents", "🕘"], ...CATEGORIES.map(([k, l, i]) => [k, l, i])];

  return (
    <div className={`relative shrink-0 ${className}`} ref={boxRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        title="Insérer un emoji"
        aria-label="Insérer un emoji"
        className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white hover:bg-amber-50 px-2.5 py-2 text-sm text-slate-600 disabled:opacity-40 disabled:cursor-not-allowed"
        data-testid={`${testId}-btn`}
      >
        <Smile className="h-4 w-4" />
      </button>
      {open && (
        <div className="absolute bottom-full right-0 z-50 mb-2 w-80 max-w-[90vw] rounded-xl border border-slate-200 bg-white shadow-2xl" data-testid={`${testId}-panel`}>
          {/* Recherche */}
          <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
            <Search className="h-3.5 w-3.5 text-slate-400" />
            <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher (merci, fête, argent…)"
              className="flex-1 text-sm outline-none" data-testid={`${testId}-search`} />
            <button type="button" onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-700" aria-label="Fermer"><X className="h-4 w-4" /></button>
          </div>
          {/* Onglets des catégories */}
          {!query && (
            <div className="flex gap-0.5 overflow-x-auto border-b border-slate-100 px-2 py-1">
              {tabs.map(([k, l, i]) => (
                <button key={k} type="button" title={l} onClick={() => setCat(k)}
                  className={`shrink-0 rounded-md px-1.5 py-1 text-lg leading-none ${cat === k ? "bg-amber-100" : "hover:bg-slate-100"}`}
                  data-testid={`${testId}-tab-${k}`}>{i}</button>
              ))}
            </div>
          )}
          {/* Grille d'emojis */}
          <div className="grid max-h-56 grid-cols-8 gap-0.5 overflow-y-auto p-2" data-testid={`${testId}-grid`}>
            {shown.length === 0 && <p className="col-span-8 py-6 text-center text-xs text-slate-400">{cat === "recent" && !query ? "Aucun emoji utilisé récemment." : "Aucun emoji trouvé."}</p>}
            {shown.map((e, i) => (
              <button key={`${e}-${i}`} type="button" onClick={() => insert(e)} title={e}
                className="rounded-md p-1 text-xl leading-none hover:bg-amber-50" data-testid={`${testId}-item`}>{e}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
