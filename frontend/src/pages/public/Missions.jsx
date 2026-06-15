import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { useI18n } from "@/contexts/I18nContext";
import { Target, Compass, Award } from "lucide-react";

export default function Missions() {
  const { lang, t } = useI18n();
  const [mission, setMission] = useState(null);
  const [about, setAbout] = useState(null);
  useEffect(() => {
    apiClient.get("/content", { params: { lang } }).then((r) => {
      const map = Object.fromEntries(r.data.map((c) => [c.slug, c]));
      setMission(map.mission);
      setAbout(map.about);
    }).catch(() => {});
  }, [lang]);
  const values = [
    { i: Target, t: t("public.missions.value1_t", "Vision claire"), d: t("public.missions.value1_d", "Comprendre vos enjeux et y répondre par des solutions pertinentes.") },
    { i: Compass, t: t("public.missions.value2_t", "Approche itérative"), d: t("public.missions.value2_d", "Livraisons fréquentes pour ajuster avec vous à chaque étape.") },
    { i: Award, t: t("public.missions.value3_t", "Engagement qualité"), d: t("public.missions.value3_d", "Code testé, documentation à jour, transparence totale.") },
  ];
  return (
    <section
      className="py-20"
      style={{
        background: "var(--block-missions-bg, transparent)",
        color: "var(--block-missions-text, inherit)",
      }}
      data-testid="missions-page"
    >
      <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
        <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">{t("public.missions.kicker", "Notre mission")}</p>
        <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white">{mission?.title || t("public.missions.title", "Notre Mission")}</h1>
        <div className="mt-8 prose-sawali text-slate-300 max-w-3xl"
             dangerouslySetInnerHTML={{ __html: mission?.body_html || "" }} />
        <div className="mt-14 grid md:grid-cols-3 gap-4">
          {values.map(({ i: Icon, t: title, d }, k) => (
            <div key={k} className="glow-card rounded-xl p-6">
              <Icon className="h-7 w-7 text-sawali-blue-light" />
              <h3 className="mt-4 text-lg font-display font-semibold text-white">{title}</h3>
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
