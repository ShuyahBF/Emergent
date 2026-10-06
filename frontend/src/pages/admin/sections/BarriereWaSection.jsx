// BarriereWaSection.jsx — Lot 63 : réglage de la « barrière » anti-rafale WhatsApp.
//
// Un correspondant qui envoie plusieurs messages sans réponse de SAWALI est arrêté :
//   - au message n° « seuil » : réponse automatique (texte + image facultative) ;
//   - au-delà : ses messages sont retenus (enregistrés, sans notification ni non-lu,
//     sans réponse de Liluvine) jusqu'à ce qu'un utilisateur de SAWALI lui réponde.
// Tout est paramétrable ici : activation, seuil, fenêtre de temps, message, image,
// prise en compte des réponses de Liluvine, numéros exemptés.
import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { absoluteFileUrl } from "@/lib/fileIcons";   // adresse complète d'un fichier du serveur

const MESSAGE_DEFAUT = "Sans réponse de votre correspondant, tout autre message de votre part ne sera pas transmis. "
  + "Instructions de l'Administrateur. Attendez une réponse avant de poursuivre SVP.";

export default function BarriereWaSection() {
  const [form, setForm] = useState(null);
  const [envoiImage, setEnvoiImage] = useState(false);
  const [enregistrement, setEnregistrement] = useState(false);
  const fichierRef = useRef(null);

  // Lecture des réglages actuels
  useEffect(() => {
    apiClient.get("/admin/settings").then((r) => {
      const s = r.data || {};
      setForm({
        wa_barriere_active: !!s.wa_barriere_active,
        wa_barriere_seuil: s.wa_barriere_seuil || 2,
        wa_barriere_fenetre_heures: s.wa_barriere_fenetre_heures || 24,
        wa_barriere_message: s.wa_barriere_message || "",
        wa_barriere_image_url: s.wa_barriere_image_url || "",
        wa_barriere_liluvine_compte: !!s.wa_barriere_liluvine_compte,
        wa_barriere_exemptes: s.wa_barriere_exemptes || "",
      });
    }).catch(() => toast.error("Réglages indisponibles"));
  }, []);

  if (!form) return <p className="text-xs text-slate-500">Patientez…</p>;
  const maj = (cle, valeur) => setForm((f) => ({ ...f, [cle]: valeur }));

  // Envoi de l'image (bibliothèque de fichiers SAWALI) puis mémorisation de son adresse
  const envoyerImage = async (fichier) => {
    if (!fichier) return;
    if (!/^image\/(png|jpe?g|webp)$/i.test(fichier.type)) { toast.error("Image PNG, JPEG ou WEBP uniquement"); return; }
    if (fichier.size > 5 * 1024 * 1024) { toast.error("Image trop lourde (5 Mo au plus)"); return; }
    setEnvoiImage(true);
    try {
      const fd = new FormData();
      fd.append("file", fichier);
      const r = await apiClient.post("/admin/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      maj("wa_barriere_image_url", r.data?.url || "");
      toast.success("Image chargée — pensez à enregistrer");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Envoi de l'image impossible");
    } finally {
      setEnvoiImage(false);
    }
  };

  // Enregistrement des réglages de la barrière
  const enregistrer = async () => {
    setEnregistrement(true);
    try {
      await apiClient.put("/admin/settings", {
        ...form,
        wa_barriere_seuil: Math.max(1, Number(form.wa_barriere_seuil) || 2),
        wa_barriere_fenetre_heures: Math.max(1, Number(form.wa_barriere_fenetre_heures) || 24),
      });
      toast.success("Barrière enregistrée");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Enregistrement impossible");
    } finally {
      setEnregistrement(false);
    }
  };

  // Aperçu : l'adresse enregistrée est relative au serveur (/api/files/…)
  const apercuImage = form.wa_barriere_image_url ? absoluteFileUrl(form.wa_barriere_image_url) : "";

  return (
    <div className="space-y-3" data-testid="barriere-wa">
      <p className="text-xs text-slate-600">
        Si un correspondant envoie plusieurs messages sans réponse de votre part : au message n° <strong>{form.wa_barriere_seuil}</strong>,
        il reçoit automatiquement le message ci-dessous (et l'image). Ses messages suivants sont retenus (visibles dans la
        conversation avec la mention « Retenu », mais sans notification ni réponse de Liluvine) jusqu'à votre réponse.
        Les commandes « ! » et les réponses à des boutons ou formulaires ne sont jamais bloquées.
      </p>

      <label className="inline-flex items-center gap-2 text-sm font-semibold">
        <input type="checkbox" checked={form.wa_barriere_active} onChange={(e) => maj("wa_barriere_active", e.target.checked)}
          data-testid="barriere-active" />
        Activer la barrière
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Nombre de messages sans réponse avant la barrière</span>
          <input type="number" min="1" value={form.wa_barriere_seuil} onChange={(e) => maj("wa_barriere_seuil", e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="barriere-seuil" />
        </label>
        <label className="block text-xs">
          <span className="font-semibold text-slate-700">Messages pris en compte : dernières … heures</span>
          <input type="number" min="1" value={form.wa_barriere_fenetre_heures} onChange={(e) => maj("wa_barriere_fenetre_heures", e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
        </label>
      </div>

      <label className="block text-xs">
        <span className="font-semibold text-slate-700">Réponse automatique (vide = message par défaut, en gris)</span>
        <textarea rows={3} value={form.wa_barriere_message} onChange={(e) => maj("wa_barriere_message", e.target.value)}
          placeholder={MESSAGE_DEFAUT} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
          data-testid="barriere-message" />
      </label>

      {/* Image envoyée avec la réponse automatique (facultative) */}
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span className="font-semibold text-slate-700">Image jointe (facultative) :</span>
        {apercuImage ? (
          <>
            <img src={apercuImage} alt="Image de la barrière" className="h-16 w-16 rounded object-cover ring-1 ring-slate-200" />
            <button type="button" onClick={() => maj("wa_barriere_image_url", "")} className="text-rose-600 hover:underline">Retirer</button>
          </>
        ) : <span className="text-slate-400">aucune</span>}
        <button type="button" disabled={envoiImage} onClick={() => fichierRef.current?.click()}
          className="rounded-lg border border-slate-300 bg-white px-2 py-1 hover:bg-slate-50 disabled:opacity-50">
          {envoiImage ? "Patientez…" : "Choisir une image…"}
        </button>
        <input ref={fichierRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
          onChange={(e) => { envoyerImage(e.target.files?.[0]); e.target.value = ""; }} />
      </div>

      <label className="inline-flex items-center gap-2 text-xs">
        <input type="checkbox" checked={form.wa_barriere_liluvine_compte}
          onChange={(e) => maj("wa_barriere_liluvine_compte", e.target.checked)} />
        Une réponse automatique de Liluvine lève aussi la barrière (sinon, seule une réponse d'un utilisateur compte)
      </label>

      <label className="block text-xs">
        <span className="font-semibold text-slate-700">Numéros jamais bloqués (séparés par des virgules)</span>
        <input value={form.wa_barriere_exemptes} onChange={(e) => maj("wa_barriere_exemptes", e.target.value)}
          placeholder="+226 70 00 00 00, +226 76 00 00 00" className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" />
      </label>

      <div className="flex justify-end">
        <button type="button" onClick={enregistrer} disabled={enregistrement}
          className="rounded-lg bg-sawali-blue px-4 py-2 text-xs font-semibold text-white hover:bg-sawali-blue-light disabled:opacity-50"
          data-testid="barriere-enregistrer">
          {enregistrement ? "Patientez…" : "Enregistrer la barrière"}
        </button>
      </div>
    </div>
  );
}
