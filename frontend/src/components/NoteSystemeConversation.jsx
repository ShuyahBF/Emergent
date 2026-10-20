// NoteSystemeConversation.jsx — Lot 262 : messages « système » dans la conversation d'un contact, VISIBLES SEULEMENT
// dans le portail (ils ne sont jamais envoyés au contact) : par exemple « Demande d'accord envoyée à Awa… ».
//
// - Les notes sont rangées sur la fiche du contact (`contact.notes_systeme`, renvoyées avec la conversation) ;
// - fusionnerNotes(messages, notes) : liste unique triée par date (tri stable), les notes étant marquées « __note » ;
// - BulleNoteSysteme : petite carte centrée, comme un message de service dans une messagerie, avec la couleur du ton
//   (ok = vert, attention = orange, erreur = rouge) et la mention « visible seulement par vous ».
import React from "react";

// Couleurs de la carte selon le ton de la note
const TONS = {
  ok: "bg-emerald-50 text-emerald-900 ring-emerald-200",
  attention: "bg-amber-50 text-amber-900 ring-amber-200",
  erreur: "bg-rose-50 text-rose-900 ring-rose-200",
};

// Date de tri d'un élément (message, appel ou note)
const dateDe = (x) => new Date(x.sonne_le || x.created_at || x.received_at || x.timestamp || 0).getTime() || 0;

// Messages (et appels) + notes système dans l'ordre chronologique (l'ordre existant est conservé à égalité)
export function fusionnerNotes(elements, notes) {
  if (!notes || notes.length === 0) return elements || [];
  const items = notes.map((n) => ({ ...n, __note: true, id: `note-${n.id}`, created_at: n.at }));
  return [...(elements || []), ...items]
    .map((x, i) => ({ x, i, t: dateDe(x) }))
    .sort((a, b) => (a.t - b.t) || (a.i - b.i))
    .map((e) => e.x);
}

// Carte d'une note dans le fil de conversation
export function BulleNoteSysteme({ n }) {
  const quand = dateDe(n) ? new Date(dateDe(n)).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "";
  return (
    <div className="flex flex-col items-center" data-testid={`note-dans-fil-${n.id}`}>
      <div className={`max-w-[90%] rounded-2xl px-3 py-2 text-xs ring-1 ${TONS[n.ton] || TONS.ok}`}>
        <p>{n.ton === "ok" ? "✅ " : n.ton === "erreur" ? "⛔ " : "⚠️ "}{n.texte}</p>
        <p className="mt-0.5 text-[10px] opacity-70">{quand}{n.par ? ` · par ${n.par}` : ""} · visible seulement par vous, jamais envoyé au contact</p>
      </div>
    </div>
  );
}
