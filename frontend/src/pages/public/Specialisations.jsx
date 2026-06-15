import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { useI18n } from "@/contexts/I18nContext";
import { Globe, Smartphone, Database, Cpu, Code2 } from "lucide-react";
import { CODE_IMG } from "@/lib/brand";

const ICONS = { Globe, Smartphone, Database, Cpu, Code: Code2 };

export default function Specialisations() {
  const { lang, t } = useI18n();
  const [spec, setSpec] = useState(null);
  // Iter40-content-i18n — Re-fetch on language change
  useEffect(() => {
    apiClient.get("/content/specialisations", { params: { lang } }).then((r) => setSpec(r.data)).catch(() => {});
  }, [lang]);
  const items = spec?.metadata?.items || [];
  return (
    <section
      className="py-20"
      style={{
        background: "var(--block-specialisations-bg, transparent)",
        color: "var(--block-specialisations-text, inherit)",
      }}
      data-testid="specialisations-page"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">{t("public.specs.kicker", "Domaines d'intervention")}</p>
        <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white">{spec?.title || t("public.specs.title", "Nos Spécialisations")}</h1>

        <div className="mt-12 grid lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 grid sm:grid-cols-2 gap-4">
            {items.map((s, i) => {
              const Icon = ICONS[s.icon] || Code2;
              return (
                <div key={i} className="glow-card rounded-xl p-6" data-testid={`spec-item-${i}`}>
                  <div className="h-10 w-10 rounded-lg bg-sawali-blue/15 border border-sawali-blue/30 flex items-center justify-center">
                    <Icon className="h-5 w-5 text-sawali-blue-light" />
                  </div>
                  <h3 className="mt-4 text-lg font-display font-semibold text-white">{s.title}</h3>
                  <p className="mt-2 text-sm text-slate-400 leading-relaxed">{s.desc}</p>
                </div>
              );
            })}
          </div>
          <div className="rounded-2xl overflow-hidden border border-white/10 self-stretch min-h-[380px] relative">
            <img src={CODE_IMG} alt="Code" className="w-full h-full object-cover" />
            <div className="absolute inset-0 bg-gradient-to-t from-[#081226]/95 via-[#081226]/40 to-transparent" />
            <div className="absolute bottom-0 p-6">
              <p className="text-sm text-sawali-blue-light uppercase tracking-[0.2em]">{t("public.specs.stack_kicker", "Stack moderne")}</p>
              <p className="text-white text-lg font-display font-semibold mt-1">{t("public.specs.stack_label", "React · FastAPI · Mongo · Cloud")}</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
