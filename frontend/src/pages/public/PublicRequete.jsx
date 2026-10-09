// PublicRequete.jsx — Lot 86.1 : page publique du LIEN PERSONNEL d'un client (/requete/<jeton>), SANS mot de passe.
// Le lien est envoyé par SAWALI au client par WhatsApp (et e-mail) ; ses agents y déposent leurs requêtes (texte,
// message vocal, photos, captures d'écran), suivent leur traitement et les évaluent. Lien révocable par SAWALI.
import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useParams } from "react-router-dom";
import { API } from "@/lib/api";
import EspaceRequetes from "@/components/EspaceRequetes";

export default function PublicRequete() {
  const { jeton } = useParams();
  const [client, setClient] = useState("");
  // Appels publics (aucun jeton de connexion : le jeton du lien suffit)
  const api = useMemo(() => {
    const base = `${API}/public/requetes/${encodeURIComponent(jeton)}`;
    return {
      charger: () => axios.get(base).then((r) => { setClient(r.data.client_nom); return r.data; }),
      deposer: (fd) => axios.post(base, fd).then((r) => r.data),
      evaluer: (id, corps) => axios.post(`${base}/${id}/evaluation`, corps),
      audio: (id) => axios.get(`${base}/${id}/audio`, { responseType: "blob" }).then((r) => r.data),
      image: (reqId, img) => axios.get(`${base}/${reqId}/images/${img.id}`, { responseType: "blob" }).then((r) => r.data),
    };
  }, [jeton]);
  useEffect(() => { document.title = "SAWALI — Vos requêtes"; }, []);
  return (
    <div className="min-h-screen bg-slate-50 p-4 md:p-8" data-testid="page-publique-requetes">
      <div className="mx-auto max-w-4xl space-y-4">
        <div className="rounded-2xl bg-sky-800 p-5 text-white shadow">
          <p className="text-xs uppercase tracking-wide text-sky-200">SAWALI Smart Systems</p>
          <h1 className="text-2xl font-bold">Vos requêtes{client ? ` — ${client}` : ""}</h1>
          <p className="mt-1 text-sm text-sky-100">Signalez un dysfonctionnement, une remarque, un souci de logiciel ou d'équipement : par écrit, par message vocal, avec des photos ou des captures d'écran (Ctrl+V). Suivez ensuite leur traitement et évaluez-les.</p>
        </div>
        <EspaceRequetes api={api} demanderNom />
        <p className="text-center text-[11px] text-slate-400">Ce lien est propre à votre structure : ne le diffusez qu'à vos agents.</p>
      </div>
    </div>
  );
}
