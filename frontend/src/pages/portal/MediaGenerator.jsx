import React from "react";
import { Sparkles, Image as ImageIcon, Video, Wand2, Hourglass } from "lucide-react";

/*
  Portal → Générateur d'Images et Vidéos
  Placeholder "Bientôt Disponible" with a colorful 8-bands gradient hero.
*/
export default function MediaGenerator() {
  return (
    <div className="space-y-8" data-testid="media-generator-page">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Création de contenu</p>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <Wand2 className="h-5 w-5 text-sawali-blue" /> Générateur d'Images et Vidéos
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Bientôt, créez des illustrations, visuels marketing et clips vidéo pour vos campagnes WhatsApp & e-mail directement depuis votre portail SAWALI.
        </p>
      </div>

      {/* Colorful 8-bands hero */}
      <div className="relative overflow-hidden rounded-3xl shadow-xl ring-1 ring-slate-200 bg-white">
        <div
          className="h-72 sm:h-96 w-full"
          style={{
            backgroundImage: [
              "linear-gradient(to right,",
              "  #ef4444 0%, #ef4444 12.5%,",         // red
              "  #f97316 12.5%, #f97316 25%,",         // orange
              "  #eab308 25%, #eab308 37.5%,",         // yellow
              "  #22c55e 37.5%, #22c55e 50%,",         // green
              "  #06b6d4 50%, #06b6d4 62.5%,",         // cyan
              "  #3b82f6 62.5%, #3b82f6 75%,",         // blue
              "  #8b5cf6 75%, #8b5cf6 87.5%,",         // violet
              "  #ec4899 87.5%, #ec4899 100%)",        // pink
            ].join(""),
          }}
          data-testid="media-generator-bands"
        />
        {/* Glass overlay */}
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6">
          <div className="rounded-full bg-white/15 backdrop-blur-md ring-1 ring-white/30 p-5 mb-5 shadow-lg">
            <Hourglass className="h-10 w-10 text-white drop-shadow" />
          </div>
          <h2 className="text-3xl sm:text-5xl font-display font-bold text-white drop-shadow-lg">
            Bientôt Disponible
          </h2>
          <p className="mt-3 text-sm sm:text-base text-white/90 max-w-md drop-shadow">
            Notre équipe finalise l'intégration. Vous serez les premiers notifiés au lancement.
          </p>
          <div className="mt-6 flex items-center gap-3 text-white/95 text-xs">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 backdrop-blur ring-1 ring-white/30 px-3 py-1.5">
              <ImageIcon className="h-3.5 w-3.5" /> Images IA
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 backdrop-blur ring-1 ring-white/30 px-3 py-1.5">
              <Video className="h-3.5 w-3.5" /> Vidéos IA
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 backdrop-blur ring-1 ring-white/30 px-3 py-1.5">
              <Sparkles className="h-3.5 w-3.5" /> Templates
            </span>
          </div>
        </div>
      </div>

      <div className="grid sm:grid-cols-3 gap-4">
        {[
          { icon: ImageIcon, title: "Visuels & flyers", desc: "Bannières WhatsApp, posts réseaux sociaux, mockups produits.", color: "bg-rose-50 text-rose-700 ring-rose-200" },
          { icon: Video, title: "Clips & démos", desc: "Vidéos courtes pour présentations, formations et campagnes.", color: "bg-sky-50 text-sky-700 ring-sky-200" },
          { icon: Wand2, title: "Édition assistée", desc: "Recadrage, fond transparent, sous-titres automatiques.", color: "bg-violet-50 text-violet-700 ring-violet-200" },
        ].map((c, i) => (
          <div key={i} className={`rounded-2xl ring-1 ${c.color} p-5`}>
            <c.icon className="h-6 w-6 mb-2" />
            <h3 className="font-display font-semibold text-slate-900">{c.title}</h3>
            <p className="text-xs text-slate-600 mt-1">{c.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
