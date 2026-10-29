/*
  Lot 361 — destinataires « Plateformes » d'un formulaire ou d'un sondage.
  Les plateformes (ALBARKA, e-Kol…) sont listées en plus des contacts : le document est transmis à leur espace Formulaires / Sondages
  (envoi signé). Une COPIE reste dans SAWALI, avec l'HISTORIQUE des transmissions affiché ci-dessous.
  API : /me/transmissions/plateformes, /me/transmissions/{formulaire|sondage}/{id} (backend/routes/transmission_plateformes.py).
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function TransmissionPlateformes({ type, docId }) {
  const [plateformes, setPlateformes] = useState([]);
  const [choisies, setChoisies] = useState([]);
  const [historique, setHistorique] = useState([]);
  const [envoi, setEnvoi] = useState(false);

  // Plateformes proposées + historique des transmissions de ce document
  const charger = useCallback(async () => {
    try {
      const [p, h] = await Promise.all([
        apiClient.get("/me/transmissions/plateformes"),
        apiClient.get(`/me/transmissions/${type}/${docId}`),
      ]);
      setPlateformes(p.data?.plateformes || []);
      setHistorique(h.data?.transmissions || []);
    } catch { /* section facultative : silence si indisponible */ }
  }, [type, docId]);
  useEffect(() => { charger(); }, [charger]);

  const bascule = (code) => setChoisies((c) => (c.includes(code) ? c.filter((x) => x !== code) : [...c, code]));

  // Transmission aux plateformes cochées
  const transmettre = async () => {
    setEnvoi(true);
    try {
      const r = await apiClient.post(`/me/transmissions/${type}/${docId}`, { plateformes: choisies });
      const ko = (r.data?.resultats || []).filter((x) => !x.ok);
      if (ko.length) toast.error(ko.map((x) => `${x.nom || x.plateforme} : ${x.erreur}`).join(" — "));
      else toast.success("Transmis aux plateformes");
      setChoisies([]);
      charger();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Transmission impossible");
    } finally {
      setEnvoi(false);
    }
  };

  if (!plateformes.length) return null;
  return (
    <section className="rounded-xl ring-1 ring-slate-200 p-3 space-y-2" data-testid="transmission-plateformes">
      <p className="text-sm font-semibold text-slate-800">Envoyer à des plateformes</p>
      <p className="text-xs text-slate-500">Le document arrive dans l'espace Formulaires / Sondages de la plateforme. Une copie reste dans SAWALI.</p>
      <div className="flex flex-wrap gap-3 text-sm">
        {plateformes.map((p) => (
          <label key={p.code} className={`inline-flex items-center gap-1.5 ${p.recoit_formulaires ? "" : "opacity-50"}`}
            title={p.recoit_formulaires ? "" : "Adresse de réception non renseignée pour cette plateforme"}>
            <input type="checkbox" disabled={!p.recoit_formulaires} checked={choisies.includes(p.code)} onChange={() => bascule(p.code)}
              data-testid={`transmission-${p.code}`} />
            {p.nom}
          </label>
        ))}
      </div>
      <button type="button" onClick={transmettre} disabled={envoi || !choisies.length} data-testid="transmission-envoyer"
        className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
        {envoi ? "Envoi…" : "Transmettre aux plateformes"}
      </button>
      {historique.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-slate-700">Historique des transmissions</p>
          <ul className="text-xs text-slate-600 divide-y divide-slate-100">
            {historique.slice(0, 20).map((h, i) => (
              <li key={i} className="py-1 flex flex-wrap gap-2">
                <span>{(h.le || "").slice(0, 16).replace("T", " ")}</span>
                <span className="font-semibold">{h.nom || h.plateforme}</span>
                <span className={h.ok ? "text-emerald-700" : "text-rose-600"}>{h.ok ? "transmis" : `échec : ${h.erreur}`}</span>
                <span className="ml-auto text-slate-400">{h.par}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
