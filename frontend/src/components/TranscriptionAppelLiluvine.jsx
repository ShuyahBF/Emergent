// TranscriptionAppelLiluvine.jsx — Lot 69 : détail d'un appel WhatsApp pris par Liluvine.
//
// Affiché sous la ligne du journal des appels et dans la carte d'appel du fil de conversation :
//   • résumé (1 à 3 lignes rédigé par Liluvine à la fin de l'appel) ;
//   • transcription complète (tours appelant / Liluvine, minute:seconde depuis le décroché) ;
//   • raison de fin, demande de rappel éventuelle et coût estimé (USD, appel entrant gratuit chez Meta).
// Le composant ne lit rien sur le serveur : il reçoit le champ « liluvine » de l'appel (/me/wa-appels).
import React from "react";

// Secondes → « m:ss »
const mmss = (s) => {
  const n = Math.max(0, Math.floor(Number(s) || 0));
  return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;
};

export default function TranscriptionAppelLiluvine({ l }) {
  if (!l) return null;
  const tours = l.transcription || [];
  return (
    <div className="space-y-1.5 text-left text-xs text-slate-700" data-testid="transcription-liluvine">
      {/* Résumé et circonstances de fin */}
      {l.resume && <p className="rounded bg-violet-50 px-2 py-1 text-violet-900 ring-1 ring-violet-100">📝 {l.resume}</p>}
      <p className="text-[11px] text-slate-500">
        {l.fin ? `Fin : ${l.fin}` : ""}
        {l.transfert_humain ? " · ⚠️ rappel demandé (tâche créée)" : ""}
        {l.cout ? ` · coût estimé ≈ ${Number(l.cout.total || 0).toFixed(3)} ${l.cout.devise || "USD"}` : ""}
        {l.latence_moyenne_s ? ` · délai de réponse moyen ${String(l.latence_moyenne_s).replace(".", ",")} s` : ""}
        {l.erreur ? ` · ${l.erreur}` : ""}
      </p>
      {/* Transcription horodatée */}
      {tours.length > 0 && (
        <ol className="max-h-64 space-y-1 overflow-auto rounded bg-white/80 p-2 ring-1 ring-slate-100">
          {tours.map((t, i) => (
            <li key={i} className={t.qui === "appelant" ? "" : "text-violet-800"}>
              <span className="mr-1 tabular-nums text-slate-400">[{mmss(t.t)}]</span>
              <strong>{t.qui === "appelant" ? "Appelant" : "Liluvine"} :</strong> {t.texte}
              {t.interrompu && <em className="ml-1 text-slate-400">(interrompue)</em>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
