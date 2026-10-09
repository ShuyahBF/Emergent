// MesRequetes.jsx — Lot 86 : « Mes requêtes » du portail client.
//
// Le client (contractuel ou non) soumet à SAWALI des dysfonctionnements, remarques, problèmes de logiciel ou
// d'équipement, PAR ÉCRIT, PAR MESSAGE VOCAL (transcrit automatiquement) et, depuis le lot 86.1, avec des PHOTOS,
// CAPTURES D'ÉCRAN (Ctrl+V) ou IMAGES. Chaque requête est numérotée par client (REQ-<code>-0001…) et horodatée ; le
// client suit l'état, les observations et le lot de correction, puis l'ÉVALUE (note 1 à 5 + commentaire).
// Lot 86.1 : encadré « Mon lien personnel » — page sans mot de passe à partager avec ses agents (WhatsApp…).
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Copy, Link2 } from "lucide-react";
import { apiClient } from "@/lib/api";
import EspaceRequetes from "@/components/EspaceRequetes";

// Appels du portail connecté (routes protégées par le jeton de connexion)
const API_PORTAIL = {
  charger: () => apiClient.get("/me/requetes").then((r) => r.data),
  deposer: (fd) => apiClient.post("/me/requetes", fd).then((r) => r.data),
  evaluer: (id, corps) => apiClient.post(`/me/requetes/${id}/evaluation`, corps),
  audio: (id) => apiClient.get(`/requetes/${id}/audio`, { responseType: "blob" }).then((r) => r.data),
  image: (reqId, img) => apiClient.get(`/requetes/${reqId}/images/${img.id}`, { responseType: "blob" }).then((r) => r.data),
};

export default function MesRequetes() {
  const [lien, setLien] = useState(null);
  useEffect(() => { apiClient.get("/me/requetes-lien").then((r) => setLien(r.data.url)).catch(() => setLien("")); }, []);
  const copier = async () => {
    try { await navigator.clipboard.writeText(lien); toast.success("Lien copié"); } catch { toast.error("Copie impossible"); }
  };
  return (
    <div className="space-y-5 p-4 md:p-6" data-testid="mes-requetes">
      <div>
        <h1 className="text-2xl font-display font-bold">Mes requêtes</h1>
        <p className="text-sm text-slate-600">Signalez un dysfonctionnement, une remarque, un souci de logiciel ou d'équipement — par écrit, par message vocal, avec des photos ou des captures d'écran. Chaque requête est numérotée et suivie jusqu'à sa correction, puis vous l'évaluez.</p>
      </div>
      {lien && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-sky-200 bg-sky-50 p-3 text-xs" data-testid="mon-lien-requetes">
          <Link2 className="h-4 w-4 text-sky-700" />
          <span className="font-semibold text-sky-900">Mon lien personnel</span>
          <span className="text-slate-600">(sans mot de passe, à partager avec vos agents) :</span>
          <a href={lien} target="_blank" rel="noreferrer" className="break-all font-mono text-sky-800 underline">{lien}</a>
          <button type="button" onClick={copier} className="inline-flex items-center gap-1 rounded border border-sky-300 bg-white px-2 py-0.5"><Copy className="h-3 w-3" /> Copier</button>
        </div>
      )}
      <EspaceRequetes api={API_PORTAIL} />
    </div>
  );
}
