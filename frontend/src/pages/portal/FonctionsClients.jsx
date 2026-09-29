/*
  Lot 34 — SMART Communications : fonctions activables par client, par l'Admin
  ET le Superviseur (/portal/smart-communications et /admin/smart-communications).

  « Formulaires et Sondages » et « OCR sur Pièces » ne sont accessibles à un client,
  et à ses utilisateurs suivis, que si elles sont activées ici (désactivées par
  défaut). Le serveur refuse l'accès sinon ; le menu du client les affiche grisées.
  Les autres fonctions de SMART Communications restent réservées à l'Admin (fiche
  client → SMART Communications).
  API : GET /supervision/fonctions-clients, PUT /supervision/fonctions-clients/{id}.
  Lot 36 — section « Liluvine — !formulaire » : tarifs (client SAWALI / numéro inconnu,
  modifiables par l'Admin) et dernières commandes WhatsApp (GET /supervision/liluvine-formulaire).
*/
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Bot, FileText, Loader2, Save, ScanText, Search, ShieldCheck } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

// Lot 36 — états d'une commande « !formulaire »
const STATUTS_LILUVINE = {
  analyse: ["Analyse", "bg-sky-100 text-sky-700"],
  en_attente_paiement: ["Attente paiement", "bg-amber-100 text-amber-800"],
  publie: ["En ligne", "bg-emerald-100 text-emerald-700"],
  erreur: ["Erreur", "bg-rose-100 text-rose-700"],
};

// Tarifs et suivi des commandes WhatsApp « !formulaire » (Liluvine)
function LiluvineFormulaire() {
  const { user } = useAuth();
  const estAdmin = user?.role === "admin";
  const [suivi, setSuivi] = useState(null);
  const [prix, setPrix] = useState({ client: "", inconnu: "" });
  const [enregistrement, setEnregistrement] = useState(false);

  useEffect(() => {
    apiClient.get("/supervision/liluvine-formulaire").then((r) => {
      setSuivi(r.data);
      setPrix({ client: r.data?.tarifs?.client ?? "", inconnu: r.data?.tarifs?.inconnu ?? "" });
    }).catch(() => setSuivi({ tarifs: {}, commandes: [] }));
  }, []);

  const enregistrer = async () => {
    setEnregistrement(true);
    try {
      const r = await apiClient.put("/supervision/liluvine-formulaire/tarifs", {
        prix_client_xof: parseInt(prix.client, 10) || 0, prix_inconnu_xof: parseInt(prix.inconnu, 10) || 0 });
      setSuivi((s) => ({ ...s, tarifs: r.data }));
      toast.success("Tarifs de « !formulaire » enregistrés");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Enregistrement impossible");
    } finally {
      setEnregistrement(false);
    }
  };

  return (
    <section className="rounded-xl bg-white ring-1 ring-slate-200 p-4 space-y-3" data-testid="liluvine-formulaire">
      <div>
        <h2 className="font-display font-semibold flex items-center gap-2"><Bot className="h-4 w-4 text-violet-600" /> Liluvine — commande WhatsApp « !formulaire »</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Un contact envoie à Liluvine un questionnaire (Word, Excel, PDF ou photo) avec la légende <b>!formulaire</b> :
          Liluvine crée le formulaire (privé), annonce le tarif, et après paiement Mobile Money envoie le lien crypté de
          saisie et celui des réponses (valables 30 jours). Tarif 0 = gratuit, mise en ligne immédiate.
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        {[["client", "Client SAWALI enregistré"], ["inconnu", "Numéro inconnu"]].map(([k, l]) => (
          <label key={k} className="text-xs text-slate-600">
            {l} (FCFA)
            <input type="number" min={0} value={prix[k]} disabled={!estAdmin} data-testid={`liluvine-prix-${k}`}
              onChange={(e) => setPrix((p) => ({ ...p, [k]: e.target.value }))}
              className="mt-1 block w-40 rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:bg-slate-50" />
          </label>
        ))}
        {estAdmin ? (
          <button onClick={enregistrer} disabled={enregistrement} data-testid="liluvine-prix-enregistrer"
            className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 text-white px-3 py-2 text-xs font-semibold hover:bg-violet-700 disabled:opacity-50">
            <Save className="h-3.5 w-3.5" /> Enregistrer
          </button>
        ) : <p className="text-[11px] text-slate-400">Tarifs modifiables par l'Admin.</p>}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-[10px] uppercase tracking-wider text-slate-500">
            <tr><th className="text-left py-1.5 pr-3">Date</th><th className="text-left pr-3">Contact</th><th className="text-left pr-3">Type</th>
              <th className="text-left pr-3">Formulaire</th><th className="text-right pr-3">Tarif</th><th className="text-left">État</th></tr>
          </thead>
          <tbody>
            {!suivi && <tr><td colSpan={6} className="py-3 text-center text-slate-400"><Loader2 className="h-3.5 w-3.5 animate-spin inline" /></td></tr>}
            {suivi && suivi.commandes.length === 0 && <tr><td colSpan={6} className="py-3 text-center text-slate-400 italic">Aucune commande pour le moment.</td></tr>}
            {(suivi?.commandes || []).map((c) => {
              const [lib, cls] = STATUTS_LILUVINE[c.statut] || [c.statut, "bg-slate-100 text-slate-600"];
              return (
                <tr key={c.id} className="border-t border-slate-100" title={c.erreur || ""}>
                  <td className="py-1.5 pr-3 whitespace-nowrap text-slate-500">{new Date(c.cree_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
                  <td className="pr-3 whitespace-nowrap">{c.nom_contact ? `${c.nom_contact} · ` : ""}{c.telephone}</td>
                  <td className="pr-3">{c.type_client === "client" ? (c.compte_libelle || "Client") : "Inconnu"}</td>
                  <td className="pr-3 font-mono">{c.titre || c.fichier}</td>
                  <td className="pr-3 text-right tabular-nums">{c.prix_xof != null ? `${c.prix_xof.toLocaleString("fr-FR")} F` : "—"}</td>
                  <td><span className={`rounded-full px-2 py-0.5 ${cls}`}>{lib}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

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

      <LiluvineFormulaire />
    </div>
  );
}
