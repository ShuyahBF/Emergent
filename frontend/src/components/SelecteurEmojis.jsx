// SelecteurEmojis.jsx — Lot 91 : bouton 😊 du chat (interne et support) pour insérer un emoji dans le message.
// Demande du propriétaire (09/10/2026) : « Pour le chat du support permettre aussi d'envoyer des emojis ».
// Aucun module externe : une petite grille d'emojis courants rangés par onglets ; l'emoji choisi est inséré à la
// position du curseur dans la zone de saisie (voir InternalChatPanel). La fenêtre se ferme au clic extérieur / Échap.
import React, { useEffect, useRef, useState } from "react";
import { Smile } from "lucide-react";

// Onglets : libellé (emoji) → liste d'emojis
const GROUPES = [
  { nom: "Visages", icone: "😊", emojis: "😀 😃 😄 😁 😆 😅 😂 🤣 😊 😇 🙂 😉 😍 🥰 😘 😋 😎 🤩 🥳 🤔 🤨 😐 😶 🙄 😏 😴 😌 😮 😲 😳 🥺 😢 😭 😤 😠 😡 🤯 😱 🤗 🤭 🤫 😬 🙃 🤒 🤕".split(" ") },
  { nom: "Gestes", icone: "👍", emojis: "👍 👎 👌 ✌️ 🤞 🤝 👏 🙌 🙏 💪 👋 🤙 👉 👈 👆 👇 ☝️ ✋ 🖐️ 👊 ✊ 🫶 🤲 ✍️".split(" ") },
  { nom: "Cœurs", icone: "❤️", emojis: "❤️ 🧡 💛 💚 💙 💜 🖤 🤍 💔 💕 💞 💓 💗 💖 💝 ✨ ⭐ 🌟 🔥 💯 🎉 🎊 🎁 🏆".split(" ") },
  { nom: "Support", icone: "🛠️", emojis: "✅ ❌ ⚠️ ❓ ❗ ⏳ ⌛ 🕐 📅 📌 📎 📝 📄 📊 📈 💡 🔧 🛠️ ⚙️ 🔒 🔑 💻 🖥️ 🖨️ 📱 ☎️ 📞 📧 💬 🔔 🚀 🐞 🆗 🆕 ➡️ ⬅️ 🔄".split(" ") },
];

export default function SelecteurEmojis({ onChoisir, disabled = false }) {
  const [ouvert, setOuvert] = useState(false);
  const [groupe, setGroupe] = useState(0);
  const boiteRef = useRef(null);

  // Fermeture au clic en dehors de la fenêtre ou avec la touche Échap
  useEffect(() => {
    if (!ouvert) return undefined;
    const clic = (e) => { if (boiteRef.current && !boiteRef.current.contains(e.target)) setOuvert(false); };
    const touche = (e) => { if (e.key === "Escape") setOuvert(false); };
    document.addEventListener("mousedown", clic);
    document.addEventListener("keydown", touche);
    return () => { document.removeEventListener("mousedown", clic); document.removeEventListener("keydown", touche); };
  }, [ouvert]);

  return (
    <div className="relative shrink-0" ref={boiteRef}>
      <button type="button" onClick={() => setOuvert((v) => !v)} disabled={disabled}
              className="inline-flex items-center justify-center h-10 w-10 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-100 disabled:opacity-40"
              title="Insérer un emoji" aria-label="Insérer un emoji" aria-expanded={ouvert} data-testid="internal-chat-emojis">
        <Smile className="h-4 w-4" />
      </button>
      {ouvert && (
        <div className="absolute bottom-full left-0 mb-2 w-[272px] rounded-xl bg-white p-2 shadow-2xl ring-1 ring-slate-200 z-10"
             role="dialog" aria-label="Emojis" data-testid="internal-chat-emojis-grille">
          {/* Onglets des groupes d'emojis */}
          <div className="mb-1 flex gap-1 border-b border-slate-100 pb-1">
            {GROUPES.map((g, i) => (
              <button key={g.nom} type="button" onClick={() => setGroupe(i)} title={g.nom} aria-label={g.nom}
                      className={`rounded-md px-2 py-0.5 text-base ${i === groupe ? "bg-sky-100" : "hover:bg-slate-100"}`}>
                {g.icone}
              </button>
            ))}
          </div>
          {/* Grille : un clic insère l'emoji (la fenêtre reste ouverte pour en ajouter d'autres) */}
          <div className="grid max-h-44 grid-cols-8 gap-0.5 overflow-y-auto">
            {GROUPES[groupe].emojis.map((e) => (
              <button key={e} type="button" onClick={() => onChoisir(e)}
                      className="rounded-md p-1 text-lg leading-none hover:bg-slate-100" aria-label={`Emoji ${e}`}>
                {e}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
