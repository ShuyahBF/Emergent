// AudioRequete.jsx — Lot 86 : lecteur du message vocal d'une requête client.
// Le fichier est servi par une route protégée (jeton de connexion) : il est donc chargé avec apiClient,
// puis lu depuis une adresse locale du navigateur (blob), libérée à la fermeture.
// Lot 86.1 : « charger » (facultatif) remplace l'appel protégé — page publique du lien personnel.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

export default function AudioRequete({ id, charger }) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    let adresse = null;
    const promesse = charger ? charger(id) : apiClient.get(`/requetes/${id}/audio`, { responseType: "blob" }).then((r) => r.data);
    promesse
      .then((blob) => { adresse = URL.createObjectURL(blob); setUrl(adresse); })
      .catch(() => setUrl(""));
    return () => { if (adresse) URL.revokeObjectURL(adresse); };
  }, [id]);
  if (url === null) return <p className="text-xs text-slate-500">Patientez… chargement du message vocal</p>;
  if (!url) return <p className="text-xs text-rose-700">Message vocal indisponible</p>;
  return <audio controls src={url} className="mt-1 h-8" />;
}
