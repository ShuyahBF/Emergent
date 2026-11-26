// ============================================================================
// HistoriqueChatInterne.jsx — Lot 467 : bloc « Chat interne » de la page Liluvine → Historique Conversation (SOUS les conversations WhatsApp).
// Même principe que WhatsApp : un CLIENT, ses POSTES Loois (liste déroulante à choix multiples), « Afficher l'historique » → les sessions d'assistance
// (ticket, agent, début, fin, DURÉE) puis les messages du chat interne du Support Loois, horodatés, du plus récent au plus ancien ; Imprimer / PDF et Exporter CSV
// (date et heure d'édition, « Liluvine » vertical sur chaque page, faits par le serveur).
// Backend : GET /api/me/liluvine-historique-support/clients et /postes?client= ; POST /api/me/liluvine-historique-support, …/pdf, …/csv.
// ============================================================================
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, Clock, FileSpreadsheet, MessagesSquare, Printer, RefreshCw, Search } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import ListeMultiChoix from "@/components/ListeMultiChoix";
import BlocRepliable from "@/components/BlocRepliable";

// Pastille du poste : texte NOIR sur fond BLANC, contour noir (comme les contacts WhatsApp)
const Pastille = ({ nom }) => (
  <span className="inline-block max-w-[16rem] truncate rounded-full border border-black bg-white px-2.5 py-0.5 text-xs font-semibold text-black" title={nom} data-testid="pastille-poste">{nom}</span>
);

export default function HistoriqueChatInterne({ clientHaut = "" }) {
  const [clients, setClients] = useState(null);            // null = chargement ; [{client, sessions}]
  const [client, setClient] = useState("");
  const [postes, setPostes] = useState([]);                // [{id, nom, sessions}]
  const [choisis, setChoisis] = useState([]);
  const [du, setDu] = useState("");
  const [au, setAu] = useState("");
  const [resultat, setResultat] = useState(null);
  const [filtre, setFiltre] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [refuse, setRefuse] = useState("");                // message si l'élément n'est pas partagé au superviseur

  // Clients ayant eu des sessions d'assistance ; on présélectionne celui choisi plus haut s'il porte le même nom
  const charger = useCallback(async () => {
    toast("Lecture des clients du support en cours…");
    try {
      const r = await apiClient.get("/me/liluvine-historique-support/clients");
      const l = Array.isArray(r.data) ? r.data : [];
      setClients(l); setRefuse("");
      const meme = l.find((c) => c.client.toLowerCase() === String(clientHaut || "").toLowerCase());
      if (meme) setClient(meme.client);
      toast.success(`${l.length} client(s) avec sessions d'assistance.`);
    } catch (e) { setClients([]); setRefuse(e?.response?.data?.detail || "Lecture impossible"); }
  }, [clientHaut]);
  useEffect(() => { charger(); }, [charger]);

  // Postes du client choisi
  useEffect(() => {
    setChoisis([]); setResultat(null);
    if (!client) { setPostes([]); return; }
    apiClient.get("/me/liluvine-historique-support/postes", { params: { client } }).then((r) => setPostes(Array.isArray(r.data) ? r.data : [])).catch(() => setPostes([]));
  }, [client]);

  const optionsPostes = useMemo(() => postes.map((p) => ({ id: p.id, label: p.nom, detail: `${p.sessions} session(s)` })), [postes]);
  const corps = useMemo(() => ({ client, poste_ids: choisis, du, au }), [client, choisis, du, au]);

  const afficher = async () => {
    if (!choisis.length) { toast.error("Cochez au moins un poste."); return; }
    setEnCours(true); toast("Patientez… lecture du chat interne en cours");
    try {
      const r = await apiClient.post("/me/liluvine-historique-support", corps);
      setResultat(r.data);
      toast.success(`${r.data.sessions.length} session(s), ${r.data.total} message(s) — durée totale ${r.data.duree_totale}.`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Lecture du chat interne impossible"); }
    finally { setEnCours(false); }
  };
  const imprimer = async () => {
    setEnCours(true); toast("Patientez… préparation du PDF en cours");
    try {
      const r = await apiClient.post("/me/liluvine-historique-support/pdf", corps, { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const f = window.open(url, "_blank");
      if (!f) { const a = document.createElement("a"); a.href = url; a.download = "historique-chat-interne.pdf"; a.click(); }
      toast.success("PDF prêt : utilisez l'impression de l'onglet qui s'ouvre.");
      setTimeout(() => URL.revokeObjectURL(url), 120000);
    } catch (e) { toast.error("Création du PDF impossible"); }
    finally { setEnCours(false); }
  };
  const exporterCsv = async () => {
    setEnCours(true); toast("Patientez… préparation du fichier CSV en cours");
    try {
      const r = await apiClient.post("/me/liluvine-historique-support/csv", corps, { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([r.data], { type: "text/csv;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url; a.download = `historique-chat-interne-${new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "")}.csv`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      toast.success("Fichier CSV exporté.");
    } catch (e) { toast.error("Export CSV impossible"); }
    finally { setEnCours(false); }
  };

  // Messages : colonnes triables (règle 19), filtre par poste ou texte
  const lignes = useMemo(() => {
    const t = filtre.trim().toLowerCase();
    const l = resultat?.messages || [];
    return t ? l.filter((m) => `${m.contact} ${m.message} ${m.sens}`.toLowerCase().includes(t)) : l;
  }, [resultat, filtre]);
  const { lignes: triees, tri, basculer } = useTri(lignes, { quand: (m) => m.quand_iso, contact: (m) => m.contact, sens: (m) => m.sens, session: (m) => m.session, message: (m) => m.message });
  const sessions = resultat?.sessions || [];
  const { lignes: sessTriees, tri: triS, basculer: basculerS } = useTri(sessions, { ticket: (s) => s.ticket, poste: (s) => s.poste, agent: (s) => s.agent, debut: (s) => s.demande_le_iso, duree: (s) => s.duree_s ?? -1, statut: (s) => s.statut });

  return (
    <BlocRepliable id="chat-interne" titre="Chat interne — Support Loois" icone={MessagesSquare} classe="border-2 border-indigo-200" resume={resultat ? `${sessions.length} session(s), ${resultat.total} message(s), ${resultat.duree_totale}` : ""}>
      <div data-testid="historique-chat-interne" className="space-y-4">
      <p className="text-sm text-slate-600">Sessions d'assistance (avec leur durée) et messages du chat interne, par client et par poste, du plus récent au plus ancien.</p>
      {refuse ? <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800" data-testid="chat-refuse">{refuse}</p> : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-sm font-semibold text-slate-700">1. Client
              <select value={client} onChange={(e) => setClient(e.target.value)} disabled={clients === null} data-testid="chat-client" className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal">
                <option value="">Choisir un client…</option>
                {(clients || []).map((c) => <option key={c.client} value={c.client}>{c.client} ({c.sessions})</option>)}
              </select></label>
            <div className="text-sm font-semibold text-slate-700">2. Postes <span className="font-normal text-slate-500">({choisis.length})</span>
              <div className="mt-1 font-normal">
                <ListeMultiChoix options={optionsPostes} valeur={choisis} onChange={setChoisis} disabled={!client} vide={client ? "Cocher des postes…" : "Choisissez d'abord un client"} pluriel="postes choisis" testid="chat-postes" />
              </div></div>
            <label className="text-sm font-semibold text-slate-700">Du (facultatif)
              <input type="date" value={du} onChange={(e) => setDu(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" data-testid="chat-du" /></label>
            <label className="text-sm font-semibold text-slate-700">Au (facultatif)
              <input type="date" value={au} onChange={(e) => setAu(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" data-testid="chat-au" /></label>
          </div>
          <div className="flex flex-wrap items-center gap-2 boutons-distincts">
            <button type="button" onClick={afficher} disabled={enCours || !choisis.length} data-testid="chat-afficher" className="inline-flex items-center gap-1 rounded-full bg-indigo-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"><Search className="h-4 w-4" /> Afficher l'historique</button>
            <button type="button" onClick={charger} disabled={enCours} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50"><RefreshCw className="h-4 w-4" /> Actualiser les postes</button>
          </div>
        </>)}

      {resultat && (
        <div className="space-y-3" data-testid="chat-resultat">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
              <b>{sessions.length}</b> session(s) · <b>{resultat.total}</b> message(s) ·
              <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 font-semibold text-indigo-800" data-testid="chat-duree-totale"><Clock className="h-3.5 w-3.5" /> Durée totale de l'assistance : {resultat.duree_totale}</span>
              {resultat.tronque && <span className="text-amber-700">limité aux {resultat.maximum} messages les plus récents : réduisez la période</span>}
              <span className="text-xs text-slate-500">édité le {new Date(resultat.genere_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</span>
            </p>
            <div className="flex flex-wrap items-center gap-2 boutons-distincts">
              <button type="button" onClick={imprimer} disabled={enCours} data-testid="chat-pdf" className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1.5 text-sm font-semibold disabled:opacity-50"><Printer className="h-4 w-4" /> Imprimer / PDF</button>
              <button type="button" onClick={exporterCsv} disabled={enCours} data-testid="chat-csv" className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1.5 text-sm font-semibold disabled:opacity-50"><FileSpreadsheet className="h-4 w-4" /> Exporter CSV</button>
            </div>
          </div>

          {/* Sessions d'assistance et leur durée */}
          <div className="max-h-72 overflow-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-sm" data-testid="chat-sessions">
              <thead className="sticky top-0 bg-slate-50"><tr className="text-left text-slate-600">
                <ThTri cle="ticket" tri={triS} onTri={basculerS}>Ticket</ThTri>
                <ThTri cle="poste" tri={triS} onTri={basculerS}>Poste</ThTri>
                <ThTri cle="agent" tri={triS} onTri={basculerS}>Agent</ThTri>
                <ThTri cle="debut" tri={triS} onTri={basculerS}>Début</ThTri>
                <th className="p-2">Fin</th>
                <ThTri cle="duree" tri={triS} onTri={basculerS} droite>Durée</ThTri>
                <ThTri cle="statut" tri={triS} onTri={basculerS}>Statut</ThTri>
              </tr></thead>
              <tbody>
                {sessTriees.map((s) => (
                  <tr key={s.id} className="border-t align-top">
                    <td className="p-2 font-semibold text-sky-700">{s.ticket || "—"}</td>
                    <td className="p-2"><Pastille nom={s.poste} /></td>
                    <td className="p-2">{s.agent || "—"}</td>
                    <td className="whitespace-nowrap p-2 tabular-nums">{s.debut}</td>
                    <td className="whitespace-nowrap p-2 tabular-nums">{s.fin}</td>
                    <td className="whitespace-nowrap p-2 text-right font-semibold tabular-nums text-indigo-800">{s.duree}</td>
                    <td className="p-2">{s.statut}</td>
                  </tr>))}
                {sessTriees.length === 0 && <tr><td colSpan={7} className="p-3 text-slate-500">Aucune session pour cette sélection.</td></tr>}
              </tbody>
              {sessions.length > 0 && <tfoot className="sticky bottom-0 bg-indigo-50 font-semibold"><tr>
                <td className="p-2">Total : {sessions.length} session(s)</td><td colSpan={4} /><td className="p-2 text-right tabular-nums text-indigo-800">{resultat.duree_totale}</td><td /></tr></tfoot>}
            </table>
          </div>

          {/* Messages du chat interne */}
          <label className="flex items-center gap-2 rounded-lg border border-slate-300 px-2 py-1 text-sm sm:w-96"><Search className="h-4 w-4 text-slate-500" />
            <input value={filtre} onChange={(e) => setFiltre(e.target.value)} placeholder="Filtrer par poste, émetteur ou texte" className="w-full p-1 outline-none" data-testid="chat-filtre" /></label>
          <div className="max-h-[32rem] overflow-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-sm" data-testid="chat-table">
              <thead className="sticky top-0 bg-slate-50"><tr className="text-left text-slate-600">
                <ThTri cle="quand" tri={tri} onTri={basculer}>Date et heure</ThTri>
                <ThTri cle="contact" tri={tri} onTri={basculer}>Poste</ThTri>
                <ThTri cle="sens" tri={tri} onTri={basculer}>Émetteur</ThTri>
                <ThTri cle="session" tri={tri} onTri={basculer}>Session</ThTri>
                <ThTri cle="message" tri={tri} onTri={basculer}>Message</ThTri>
              </tr></thead>
              <tbody>
                {triees.map((m, i) => (
                  <tr key={`${m.id}-${i}`} className="border-t align-top">
                    <td className="whitespace-nowrap p-2 tabular-nums text-slate-700">{m.quand}</td>
                    <td className="p-2"><Pastille nom={m.contact} /></td>
                    <td className="whitespace-nowrap p-2">{m.sens === "Poste"
                      ? <span className="inline-flex items-center gap-1 text-sky-700"><ArrowDownLeft className="h-4 w-4" /> Poste</span>
                      : <span className="inline-flex items-center gap-1 text-emerald-700"><ArrowUpRight className="h-4 w-4" /> {m.sens}</span>}</td>
                    <td className="whitespace-nowrap p-2 text-slate-600">{m.session}</td>
                    <td className="whitespace-pre-wrap break-words p-2">{m.message || <span className="italic text-slate-400">(sans texte)</span>}</td>
                  </tr>))}
                {triees.length === 0 && <tr><td colSpan={5} className="p-3 text-slate-500">Aucun message pour cette sélection.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>)}
      </div>
    </BlocRepliable>
  );
}
