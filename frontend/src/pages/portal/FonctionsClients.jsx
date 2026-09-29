/*
  Lot 34 — SMART Communications : fonctions activables par client, par l'Admin
  ET le Superviseur (/portal/smart-communications et /admin/smart-communications).

  « Formulaires et Sondages » et « OCR sur Pièces » ne sont accessibles à un client,
  et à ses utilisateurs suivis, que si elles sont activées ici (désactivées par
  défaut). Le serveur refuse l'accès sinon ; le menu du client les affiche grisées.
  Les autres fonctions de SMART Communications restent réservées à l'Admin (fiche
  client → SMART Communications).
  API : GET /supervision/fonctions-clients, PUT /supervision/fonctions-clients/{id}.
*/
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { FileText, Loader2, ScanText, Search, ShieldCheck } from "lucide-react";
import { apiClient } from "@/lib/api";

// Colonnes de la page (mêmes clés que le serveur)
const FONCTIONS = [
  { cle: "forms_surveys", label: "Formulaires et Sondages", icon: FileText, couleur: "bg-indigo-600" },
  { cle: "ocr_pieces", label: "OCR sur Pièces", icon: ScanText, couleur: "bg-teal-600" },
];

// Interrupteur accessible (bouton à bascule)
function Interrupteur({ actif, occupe, onChange, couleur, testId, libelle }) {
  return (
    <button type="button" role="switch" aria-checked={actif} aria-label={libelle} disabled={occupe}
      onClick={() => onChange(!actif)} data-testid={testId}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition disabled:opacity-50 ${actif ? couleur : "bg-slate-300"}`}>
      <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition ${actif ? "translate-x-5" : "translate-x-0.5"}`} />
    </button>
  );
}

export default function FonctionsClients() {
  const [clients, setClients] = useState([]);
  const [chargement, setChargement] = useState(true);
  const [recherche, setRecherche] = useState("");
  const [enCours, setEnCours] = useState("");          // "<client>:<clé>" en cours d'enregistrement

  useEffect(() => {
    apiClient.get("/supervision/fonctions-clients")
      .then((r) => setClients(r.data?.clients || []))
      .catch((e) => toast.error(e?.response?.data?.detail || "Impossible de charger les clients"))
      .finally(() => setChargement(false));
  }, []);

  // Recherche : nom, société, e-mail ou code client
  const affiches = useMemo(() => {
    const q = recherche.trim().toLowerCase();
    return clients.filter((c) => !q || [c.company, c.full_name, c.email, c.client_code]
      .some((v) => (v || "").toLowerCase().includes(q)));
  }, [clients, recherche]);

  // Totaux par fonction (bandeau du haut)
  const totaux = useMemo(() => Object.fromEntries(FONCTIONS.map((f) => [f.cle, clients.filter((c) => c[f.cle]).length])), [clients]);

  // Bascule d'une fonction pour un client : enregistrée aussitôt
  const basculer = async (client, cle, valeur) => {
    setEnCours(`${client.id}:${cle}`);
    try {
      const r = await apiClient.put(`/supervision/fonctions-clients/${client.id}`, { [cle]: valeur });
      setClients((liste) => liste.map((c) => (c.id === client.id ? { ...c, ...r.data } : c)));
      const f = FONCTIONS.find((x) => x.cle === cle);
      toast.success(`Fonction « ${f.label} » ${valeur ? "activée" : "désactivée"} pour ${client.company || client.full_name || client.email}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Modification impossible");
    } finally {
      setEnCours("");
    }
  };

  return (
    <div className="max-w-5xl space-y-5" data-testid="fonctions-clients-page">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">SMART Communications</p>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-fuchsia-600" /> Fonctions par client
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Activez pour chaque client les fonctions <b>Formulaires et Sondages</b> et <b>OCR sur Pièces</b>.
          Elles sont désactivées par défaut ; leurs utilisateurs suivis en héritent. L'Admin et le Superviseur y ont
          toujours accès.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-xl bg-white ring-1 ring-slate-200 p-3">
          <p className="text-[11px] uppercase tracking-wider text-slate-500">Clients</p>
          <p className="text-2xl font-bold tabular-nums text-slate-800">{clients.length}</p>
        </div>
        {FONCTIONS.map((f) => (
          <div key={f.cle} className="rounded-xl bg-white ring-1 ring-slate-200 p-3">
            <p className="text-[11px] uppercase tracking-wider text-slate-500">{f.label}</p>
            <p className="text-2xl font-bold tabular-nums text-slate-800">{totaux[f.cle] || 0} <span className="text-sm font-normal text-slate-500">activé(s)</span></p>
          </div>
        ))}
      </div>

      <div className="relative max-w-sm">
        <Search className="h-4 w-4 text-slate-400 absolute left-3 top-2.5" />
        <input value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Rechercher un client (nom, e-mail, code)…"
          className="w-full rounded-lg border border-slate-300 pl-9 pr-3 py-2 text-sm" data-testid="fonctions-clients-recherche" />
      </div>

      <div className="rounded-xl bg-white ring-1 ring-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="text-left px-4 py-2">Client</th>
              {FONCTIONS.map((f) => (
                <th key={f.cle} className="px-4 py-2 text-center whitespace-nowrap">
                  <span className="inline-flex items-center gap-1"><f.icon className="h-3.5 w-3.5" /> {f.label}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {chargement && (
              <tr><td colSpan={3} className="px-4 py-6 text-center text-slate-400"><Loader2 className="h-4 w-4 animate-spin inline" /> Chargement…</td></tr>
            )}
            {!chargement && affiches.length === 0 && (
              <tr><td colSpan={3} className="px-4 py-6 text-center text-slate-400 italic">Aucun client.</td></tr>
            )}
            {affiches.map((c) => (
              <tr key={c.id} className="border-t border-slate-100" data-testid={`fonctions-client-${c.id}`}>
                <td className="px-4 py-2">
                  <p className="font-medium text-slate-800">{c.company || c.full_name || c.email}</p>
                  <p className="text-xs text-slate-500">{[c.client_code, c.full_name !== c.company ? c.full_name : null, c.email].filter(Boolean).join(" · ")}</p>
                </td>
                {FONCTIONS.map((f) => (
                  <td key={f.cle} className="px-4 py-2 text-center">
                    <Interrupteur actif={!!c[f.cle]} occupe={enCours === `${c.id}:${f.cle}`} couleur={f.couleur}
                      libelle={`${f.label} — ${c.company || c.full_name || c.email}`}
                      testId={`fonction-${c.id}-${f.cle}`} onChange={(v) => basculer(c, f.cle, v)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
