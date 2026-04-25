import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Target, Compass, Award } from "lucide-react";

export default function Missions() {
  const [mission, setMission] = useState(null);
  const [about, setAbout] = useState(null);
  useEffect(() => {
    apiClient.get("/content").then((r) => {
      const map = Object.fromEntries(r.data.map((c) => [c.slug, c]));
      setMission(map.mission);
      setAbout(map.about);
    }).catch(() => {});
  }, []);
  return (
    <section className="py-20" data-testid="missions-page">
      <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
        <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">Notre mission</p>
        <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white">{mission?.title || "Notre Mission"}</h1>
        <div className="mt-8 prose-sawali text-slate-300 max-w-3xl"
             dangerouslySetInnerHTML={{ __html: mission?.body_html || "" }} />
        <div className="mt-14 grid md:grid-cols-3 gap-4">
          {[
            { i: Target, t: "Vision claire", d: "Comprendre vos enjeux et y répondre par des solutions pertinentes." },
            { i: Compass, t: "Approche itérative", d: "Livraisons fréquentes pour ajuster avec vous à chaque étape." },
            { i: Award, t: "Engagement qualité", d: "Code testé, documentation à jour, transparence totale." },
          ].map(({ i: Icon, t, d }, k) => (
            <div key={k} className="glow-card rounded-xl p-6">
              <Icon className="h-7 w-7 text-sawali-blue-light" />
              <h3 className="mt-4 text-lg font-display font-semibold text-white">{t}</h3>
              <p className="mt-2 text-sm text-slate-400">{d}</p>
            </div>
          ))}
        </div>

        {about && (
          <div className="mt-16">
            <h2 className="text-2xl font-display font-bold text-white">{about.title}</h2>
            <div className="mt-4 prose-sawali text-slate-300" dangerouslySetInnerHTML={{ __html: about.body_html }} />
          </div>
        )}
      </div>
    </section>
  );
}
