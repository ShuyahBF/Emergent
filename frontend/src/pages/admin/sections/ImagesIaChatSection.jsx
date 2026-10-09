// ImagesIaChatSection.jsx — Lot 87 : rubrique « 🎨 Images IA du chat de support » des Paramètres.
// Réglages (activé, images par heure et par personne, style proposé par défaut), état sur 7 jours
// et mode d'emploi (le bouton 🎨 se trouve dans la zone de saisie du chat interne / Support Loois).
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

// Libellés des styles (mêmes clés que le serveur)
const STYLES = { illustration: "Illustration", photo: "Photo réaliste", schema: "Schéma / pictogrammes", libre: "Libre (sans consigne)" };

export default function ImagesIaChatSection() {
  const [reg, setReg] = useState(null);        // réglages + statistiques renvoyés par le serveur
  const [enreg, setEnreg] = useState(false);

  // Lecture des réglages au chargement de la rubrique
  useEffect(() => {
    apiClient.get("/admin/chat-image-ia").then((r) => setReg(r.data)).catch(() => setReg({ erreur: true }));
  }, []);

  // Enregistrement d'un réglage modifié
  const enregistrer = async (maj) => {
    setEnreg(true);
    try {
      const r = await apiClient.put("/admin/chat-image-ia", maj);
      setReg(r.data);
      toast.success("Réglage enregistré");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Enregistrement impossible");
    } finally {
      setEnreg(false);
    }
  };

  if (!reg) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (reg.erreur) return <p className="text-sm text-rose-600">Réglages indisponibles (réservés à l'équipe SAWALI).</p>;
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-images-ia-chat">
      <p className="text-xs text-slate-600">
        Dans la fenêtre de support (chat interne, espace « Support Loois »), le bouton <b>🎨</b> de la zone de saisie ouvre une
        fenêtre où l'on décrit l'image voulue : l'IA la dessine, on peut l'<b>annoter</b> (flèches, cercles, texte, flou), puis
        l'<b>envoyer dans la discussion</b> ou la <b>transférer</b> à n'importe qui (autre discussion, WhatsApp, e-mail),
        tout de suite ou à une <b>date et une heure planifiées</b>. Toute image du chat peut aussi être transférée depuis son
        agrandissement (« ↪ Transférer »). Le bouton <b>📅</b> du chat (et « Joindre mes disponibilités » de la fenêtre 🎨)
        ajoute le lien de votre agenda (créneaux libres, sans détail) au message, comme dans la discussion WhatsApp. Réservé à l'administration, aux superviseurs et au compte du support.
      </p>
      <div className="grid gap-3 text-sm sm:grid-cols-3">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={reg.actif} disabled={enreg} onChange={(e) => enregistrer({ actif: e.target.checked })}
                 data-testid="images-ia-actif" />
          Génération activée
        </label>
        <label className="flex items-center gap-2">
          Images par heure et par personne
          <input type="number" min={1} max={200} defaultValue={reg.par_heure} disabled={enreg}
                 onBlur={(e) => Number(e.target.value) !== reg.par_heure && enregistrer({ par_heure: Number(e.target.value) })}
                 className="w-20 rounded border border-slate-300 px-2 py-1" data-testid="images-ia-par-heure" />
        </label>
        <label className="flex items-center gap-2">
          Style proposé
          <select value={reg.style} disabled={enreg} onChange={(e) => enregistrer({ style: e.target.value })}
                  className="rounded border border-slate-300 px-2 py-1" data-testid="images-ia-style">
            {Object.entries(STYLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
      </div>
      <div className="grid gap-2 text-sm sm:grid-cols-3">
        <div className="rounded-lg bg-violet-50 p-2"><p className="text-[11px] text-slate-500">Images générées (7 j)</p><p className="font-semibold">{reg.stats_7j?.generees ?? 0}</p></div>
        <div className="rounded-lg bg-emerald-50 p-2"><p className="text-[11px] text-slate-500">Envoyées dans le chat (7 j)</p><p className="font-semibold">{reg.stats_7j?.envoyees ?? 0}</p></div>
        <div className="rounded-lg bg-sky-50 p-2"><p className="text-[11px] text-slate-500">Transferts réussis (7 j)</p><p className="font-semibold">{reg.stats_7j?.transferts ?? 0}</p></div>
      </div>
      <p className="text-[11px] text-slate-500">
        Coût : chaque image est facturée par le fournisseur d'IA (clé OPENAI_API_KEY). WhatsApp n'accepte une image libre que si la
        personne a écrit depuis moins de 24 h ; sinon, transférez-la par e-mail.
      </p>
    </div>
  );
}
