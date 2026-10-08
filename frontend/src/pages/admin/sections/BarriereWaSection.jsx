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
import { Link } from "react-router-dom";   // lot 79.6 : bouton vers l'écran « Messages bloqués »

const MESSAGE_DEFAUT = "Sans réponse de votre correspondant, tout autre message de votre part ne sera pas transmis. "
  + "Instructions de l'Administrateur. Attendez une réponse avant de poursuivre SVP.";

export default function BarriereWaSection() {
  const [form, setForm] = useState(null);
  const [envoiImage, setEnvoiImage] = useState(false);
  const [enregistrement, setEnregistrement] = useState(false);
  // Lot 64.2 — diagnostic pour un numéro
  const [numeroTest, setNumeroTest] = useState("");
  const [diag, setDiag] = useState(null);
  const [diagEnCours, setDiagEnCours] = useState(false);
  const [rattachement, setRattachement] = useState(false);
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
        // Lot 64.16 — couleurs du bandeau « messages retenus » dans la conversation
        wa_barriere_bandeau_fond: s.wa_barriere_bandeau_fond || "#1d4ed8",
        wa_barriere_bandeau_texte: s.wa_barriere_bandeau_texte || "#ffffff",
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

  // Lot 64.2 — que ferait la barrière au prochain message de ce numéro, et pourquoi ?
  const verifierNumero = async () => {
    if (!numeroTest.trim()) { toast.error("Saisissez un numéro"); return; }
    setDiagEnCours(true);
    try {
      const r = await apiClient.get("/admin/barriere-wa/diagnostic", { params: { numero: numeroTest } });
      setDiag(r.data);
    } catch (err) {
      setDiag(null);
      toast.error(err?.response?.data?.detail || "Diagnostic impossible");
    } finally {
      setDiagEnCours(false);
    }
  };

  // Lot 64.14 — rattache à MA fiche les messages de ce numéro rangés sur la fiche d'un autre compte
  const rattacher = async () => {
    if (!window.confirm("Rattacher à votre fiche les messages de ce numéro rangés chez un autre compte ? "
      + "Votre fiche deviendra la fiche prioritaire pour ce numéro (les prochains messages y arriveront).")) return;
    setRattachement(true);
    try {
      const r = await apiClient.post("/admin/barriere-wa/rattacher", null, { params: { numero: numeroTest } });
      toast.success(`${r.data?.rattaches || 0} message(s) rattaché(s) à la fiche « ${r.data?.fiche} »`);
      await verifierNumero();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Rattachement impossible");
    } finally {
      setRattachement(false);
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

      {/* Lot 79.6 — tous les messages retenus, tous correspondants confondus (menu Liluvine → Messages bloqués) */}
      <Link to="/admin/liluvine-messages-bloques" data-testid="ouvrir-messages-bloques"
        className="inline-flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-md bg-blue-700 text-white hover:bg-blue-800">
        🚧 Voir tous les messages bloqués
      </Link>

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

      {/* Lot 64.16 — couleurs du bandeau de signalement dans la conversation WhatsApp, avec aperçu */}
      <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200 text-xs">
        <p className="mb-2 font-semibold text-slate-700">Couleurs du bandeau de signalement (conversation WhatsApp)</p>
        <div className="flex flex-wrap items-center gap-4">
          <label className="inline-flex items-center gap-2">Fond
            <input type="color" value={form.wa_barriere_bandeau_fond} onChange={(e) => maj("wa_barriere_bandeau_fond", e.target.value)}
              className="h-8 w-12 cursor-pointer rounded border border-slate-300" data-testid="barriere-bandeau-fond" />
          </label>
          <label className="inline-flex items-center gap-2">Texte
            <input type="color" value={form.wa_barriere_bandeau_texte} onChange={(e) => maj("wa_barriere_bandeau_texte", e.target.value)}
              className="h-8 w-12 cursor-pointer rounded border border-slate-300" data-testid="barriere-bandeau-texte" />
          </label>
          <button type="button" onClick={() => { maj("wa_barriere_bandeau_fond", "#1d4ed8"); maj("wa_barriere_bandeau_texte", "#ffffff"); }}
            className="text-sky-700 hover:underline">Couleurs par défaut (bleu / blanc)</button>
        </div>
        {/* Aperçu du bandeau tel qu'il apparaîtra dans la conversation */}
        <div className="mt-2 flex items-center justify-between rounded px-3 py-2"
          style={{ background: form.wa_barriere_bandeau_fond, color: form.wa_barriere_bandeau_texte }}>
          <span>🚧 <strong>3</strong> message(s) de ce contact retenu(s) par la barrière anti-rafale</span>
          <span className="rounded border px-2 py-0.5 font-semibold"
            style={{ background: form.wa_barriere_bandeau_texte, color: form.wa_barriere_bandeau_fond, borderColor: form.wa_barriere_bandeau_texte }}>
            Insérer dans la conversation
          </span>
        </div>
      </div>

      {/* Lot 64.2 — diagnostic : état de la barrière pour un numéro (réglages ENREGISTRÉS) */}
      <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
        <p className="mb-2 text-xs font-semibold text-slate-700">Vérifier un numéro (selon les réglages enregistrés)</p>
        <div className="flex flex-wrap items-center gap-2">
          <input value={numeroTest} onChange={(e) => setNumeroTest(e.target.value)} placeholder="+226 70 00 00 00"
            onKeyDown={(e) => { if (e.key === "Enter") verifierNumero(); }}
            className="w-56 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="barriere-numero-test" />
          <button type="button" onClick={verifierNumero} disabled={diagEnCours}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold hover:bg-slate-50 disabled:opacity-50">
            {diagEnCours ? "Patientez…" : "Vérifier"}
          </button>
        </div>
        {diag && (
          <div className="mt-2 text-xs text-slate-700" data-testid="barriere-diagnostic">
            <p className={`font-semibold ${diag.decision === "normal" ? "text-emerald-700" : diag.decision === "avertir" ? "text-amber-700" : "text-rose-700"}`}>
              {diag.explication}
            </p>
            {diag.active && (
              <p className="mt-1 text-slate-500">
                Messages reçus sans réponse : <strong>{diag.messages_sans_reponse}</strong> (seuil {diag.seuil}, fenêtre {diag.fenetre_heures} h)
                {" · "}Dernière réponse prise en compte : {diag.derniere_reponse_le
                  ? `${new Date(diag.derniere_reponse_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}${diag.derniere_reponse_par ? ` par ${diag.derniere_reponse_par}` : ""}`
                  : "aucune"}
              </p>
            )}
            {/* Lot 64.14 — messages rangés chez un autre compte : bouton de rattachement */}
            {(diag.echanges || []).some((e) => e.visible === false) && (
              <div className="mt-2 flex flex-wrap items-center gap-2 rounded bg-rose-50 p-2 text-rose-800" data-testid="alerte-autre-compte">
                <span>Des messages de ce numéro sont rangés sur la fiche d'un autre compte : vous ne les voyez pas dans la conversation.</span>
                <button type="button" onClick={rattacher} disabled={rattachement}
                  className="rounded-lg bg-rose-600 px-3 py-1 font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
                  data-testid="rattacher-ma-fiche">
                  {rattachement ? "Patientez…" : "Rattacher à ma fiche"}
                </button>
              </div>
            )}
            {/* Lot 64.4 — 10 derniers échanges avec ce numéro et leur effet sur la barrière */}
            {(diag.echanges || []).length > 0 && (
              <table className="mt-2 w-full text-[11px]">
                <thead>
                  <tr className="text-left text-slate-500"><th className="pr-2">Date</th><th className="pr-2">Sens</th><th className="pr-2">Texte</th><th className="pr-2">Par</th><th className="pr-2">Fiche</th><th>Effet</th></tr>
                </thead>
                <tbody>
                  {diag.echanges.map((e, k) => (
                    <tr key={k} className="border-t border-slate-200">
                      <td className="pr-2 whitespace-nowrap">{e.le ? new Date(e.le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : ""}</td>
                      <td className="pr-2">{e.sens}</td>
                      <td className="pr-2 max-w-[260px] truncate">{e.texte}</td>
                      <td className="pr-2">{e.par || "—"}</td>
                      {/* Lot 64.11 — message rattaché à une fiche hors de votre périmètre : invisible chez vous */}
                      <td className={`pr-2 ${e.visible === false ? "font-semibold text-rose-700" : ""}`}>
                        {e.contact || "—"}{e.visible === false ? " (autre compte : invisible chez vous)" : ""}
                      </td>
                      <td>{e.retenu ? "Retenu" : e.leve_la_barriere ? "Lève la barrière" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

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
