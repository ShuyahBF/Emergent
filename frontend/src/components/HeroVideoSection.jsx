import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { PlayCircle } from "lucide-react";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";
function absoluteUrl(u) {
  if (!u) return u;
  if (u.startsWith("http")) return u;
  return `${BACKEND}${u.startsWith("/") ? "" : "/"}${u}`;
}

export default function HeroVideoSection() {
  const [video, setVideo] = useState(null);

  useEffect(() => {
    apiClient.get("/company-info").then((r) => {
      const v = r.data?.hero_video;
      if (v && v.enabled && v.url) setVideo(v);
    }).catch(() => {});
  }, []);

  if (!video) return null;

  return (
    <section className="relative bg-slate-50 py-20 sm:py-24" data-testid="hero-video-section">
      <div className="max-w-6xl mx-auto px-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-[0.3em] text-sawali-blue mb-3">
          <PlayCircle className="h-4 w-4" /> En vidéo
        </div>
        {video.title && (
          <h2 className="text-4xl sm:text-5xl font-display font-bold tracking-tight max-w-3xl mb-4 text-slate-900">
            {video.title}
          </h2>
        )}
        {video.description && (
          <p className="text-base sm:text-lg text-slate-600 max-w-2xl mb-8">
            {video.description}
          </p>
        )}
        <div className="relative rounded-2xl overflow-hidden shadow-2xl bg-slate-900 ring-1 ring-slate-200">
          <video
            src={absoluteUrl(video.url)}
            poster={video.poster_url ? absoluteUrl(video.poster_url) : undefined}
            controls
            autoPlay={video.autoplay !== false}
            loop={video.loop !== false}
            muted={video.muted !== false}
            playsInline
            className="w-full h-auto block"
            data-testid="hero-video-player"
          >
            Votre navigateur ne prend pas en charge la lecture vidéo.
          </video>
        </div>
      </div>
    </section>
  );
}
