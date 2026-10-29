// MainHumaineSection.jsx — Lot 343 : « laisser la main aux humains » avant toute réponse automatique de l'agent IA.
//
// Règle du propriétaire : Liluvine et les autres agents IA ne répondent qu'au bout de N secondes (15 par défaut), et
// seulement si aucun humain n'a répondu à ce message. Ils ne se mêlent pas d'une conversation menée par un humain,
// sauf si plus aucun humain n'est présent dans le centre de messagerie. Les commandes « ! » restent immédiates.
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function MainHumaineSection() {
  const [form, setForm] = useState(null);
  const [enregistrement, setEnregistrement] = useState(false);

  // Lecture des réglages actuels (valeurs par défaut : actif, 15 s, 30 min)
  useEffect(() => {
    apiClient.get("/admin/settings").then((r) => {
      const s = r.data || {};
      setForm({
        wa_main_humaine_active: s.wa_main_humaine_active == null ? true : !!s.wa_main_humaine_active,
        wa_main_humaine_delai_s: s.wa_main_humaine_delai_s ?? 15,
        wa_main_humaine_fenetre_min: s.wa_main_humaine_fenetre_min ?? 30,
      });
    }).catch(() => toast.error("Réglages indisponibles"));
  }, []);

  if (!form) return <p className="text-xs text-slate-500">Patientez…</p>;
  const maj = (cle, valeur) => setForm((f) => ({ ...f, [cle]: valeur }));

  // Enregistrement des trois réglages
  const enregistrer = async () => {
    setEnregistrement(true);
    try {
      await apiClient.put("/admin/settings", {
        wa_main_humaine_active: form.wa_main_humaine_active,
        wa_main_humaine_delai_s: Math.max(0, Math.min(120, Number(form.wa_main_humaine_delai_s) || 0)),
        wa_main_humaine_fenetre_min: Math.max(1, Number(form.wa_main_humaine_fenetre_min) || 30),
      });
      toast.success("Réglages enregistrés");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Enregistrement impossible");
    } finally {
      setEnregistrement(false);
    }
  };

  const champ = "w-24 rounded-md border border-slate-300 px-2 py-1 text-sm";
  return (
    <div className="space-y-3" data-testid="main-humaine">
      <p className="text-xs text-slate-600">
        La réponse automatique de l'agent IA n'est envoyée qu'après <strong>{form.wa_main_humaine_delai_s} s</strong>, et seulement si aucun
        humain n'a répondu entre-temps. Si un humain mène déjà la conversation, l'IA se tait tant qu'un membre de l'équipe est présent
        dans le centre de messagerie (session ouverte, activité il y a 5 minutes au plus). Les commandes « ! » restent immédiates.
      </p>
      <label className="inline-flex items-center gap-2 text-sm font-semibold">
        <input type="checkbox" checked={form.wa_main_humaine_active} onChange={(e) => maj("wa_main_humaine_active", e.target.checked)}
          data-testid="main-humaine-active" />
        Laisser la main aux humains
      </label>
      <div className="flex flex-wrap gap-4 text-sm">
        <label className="flex flex-col gap-1">
          Délai avant la réponse de l'IA (secondes, 0 = immédiat)
          <input type="number" min={0} max={120} className={champ} value={form.wa_main_humaine_delai_s}
            onChange={(e) => maj("wa_main_humaine_delai_s", e.target.value)} data-testid="main-humaine-delai" />
        </label>
        <label className="flex flex-col gap-1">
          Conversation « en cours » : dernier message humain depuis (minutes)
          <input type="number" min={1} className={champ} value={form.wa_main_humaine_fenetre_min}
            onChange={(e) => maj("wa_main_humaine_fenetre_min", e.target.value)} data-testid="main-humaine-fenetre" />
        </label>
      </div>
      <button type="button" onClick={enregistrer} disabled={enregistrement} data-testid="main-humaine-enregistrer"
        className="text-xs font-semibold px-3 py-1.5 rounded-md bg-blue-700 text-white hover:bg-blue-800 disabled:opacity-50">
        {enregistrement ? "Patientez…" : "Enregistrer"}
      </button>
    </div>
  );
}
