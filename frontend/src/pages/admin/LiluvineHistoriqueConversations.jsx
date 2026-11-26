// ============================================================================
// LiluvineHistoriqueConversations.jsx — Lot 466 : sous-menu Liluvine « Historique Conversation ».
// 1) on choisit le CLIENT (même liste que « Tous les clients » du Centre de Messagerie) ; 2) tous ses contacts sont proposés dans une liste déroulante à choix multiples ;
// 3) « Afficher » : EN BAS, toutes les conversations WhatsApp de ces contacts, horodatées, de la plus récente à la plus ancienne (messages bloqués ignorés) ;
//    une pastille NOIR sur BLANC donne le nom du contact. « Imprimer / PDF » et « Exporter CSV » : mêmes données, mise en page faite par le serveur
//    (date et heure d'édition, « Liluvine » écrit verticalement en bas de chaque page).
// Accès : administrateur, et superviseur auquel l'élément « Historique des conversations WhatsApp » est partagé (Paramètres → Liluvine — partage avec les superviseurs).
// Lot 467 : sous les conversations WhatsApp, un bloc à part « Chat interne — Support Loois » (components/HistoriqueChatInterne.jsx).
// Backend : POST /api/me/liluvine-historique, …/pdf, …/csv ; contacts = GET /api/me/contacts (même périmètre que le Centre de Messagerie).
// ============================================================================
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, FileDown, FileSpreadsheet, History, Printer, RefreshCw, Search } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import ListeMultiChoix from "@/components/ListeMultiChoix";
import BlocRepliable from "@/components/BlocRepliable";   // lot 467 : blocs repliables
import HistoriqueChatInterne from "@/components/HistoriqueChatInterne";   // lot 467 : bloc à part pour le chat interne (support)

// Options de client : MÊME règle que le Centre de Messagerie (code — nom, puis les sociétés déjà saisies sur des contacts), triées par libellé
function optionsClients(clients, contacts) {
  const vus = new Set(), opts = [];
  (clients || []).forEach((c) => {
    const code = c.client_code || "", nom = c.company || c.full_name || "";
    const cle = (code || nom).toLowerCase();
    if (!cle || vus.has(cle)) return;
    vus.add(cle);
    opts.push({ valeur: nom || code, label: code ? `${code} — ${nom}` : nom });
  });
  (contacts || []).forEach((c) => {
    const cle = (c.company || "").toLowerCase();
    if (!cle || vus.has(cle)) return;
    vus.add(cle);
    opts.push({ valeur: c.company, label: c.company });
  });
  return opts.sort((a, b) => a.label.localeCompare(b.label));
}

// Pastille du contact : texte NOIR sur fond BLANC, contour noir (demande du propriétaire)
const Pastille = ({ nom }) => (
  <span className="inline-block max-w-[16rem] truncate rounded-full border border-black bg-white px-2.5 py-0.5 text-xs font-semibold text-black" title={nom} data-testid="pastille-contact">{nom}</span>
);

export default function LiluvineHistoriqueConversations() {
  const [contacts, setContacts] = useState(null);       // null = chargement
  const [clients, setClients] = useState([]);
  const [client, setClient] = useState("");              // valeur de la société choisie
  const [choisis, setChoisis] = useState([]);            // id des contacts cochés (sans doublon)
  const [du, setDu] = useState("");
  const [au, setAu] = useState("");
  const [resultat, setResultat] = useState(null);        // { total, tronque, maximum, contacts, ignores, messages, genere_le }
  const [enCours, setEnCours] = useState(false);
  const [filtre, setFiltre] = useState("");

  const charger = useCallback(async () => {
    toast("Lecture des contacts en cours…");
    try {
      const [c, r] = await Promise.all([apiClient.get("/me/contacts", { params: { avec_bloques: true } }), apiClient.get("/me/clients-roster").catch(() => ({ data: [] }))]);
      setContacts(Array.isArray(c.data) ? c.data : []); setClients(r.data || []);
      toast.success(`${(Array.isArray(c.data) ? c.data : []).length} contact(s) lus.`);
    } catch (e) { setContacts([]); toast.error(e?.response?.data?.detail || "Lecture des contacts impossible"); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const clientsOptions = useMemo(() => optionsClients(clients, contacts), [clients, contacts]);
  const contactsDuClient = useMemo(() => (client ? (contacts || []).filter((c) => (c.company || "") === client) : []), [contacts, client]);
  const optionsContacts = useMemo(() => contactsDuClient.map((c) => ({ id: c.id, label: c.name || c.whatsapp || c.phone || "Contact sans nom", detail: (c.whatsapp || c.phone || "") + (c.bloque_le ? " · ⛔ bloqué" : "") })), [contactsDuClient]);
  const libelleClient = clientsOptions.find((o) => o.valeur === client)?.label || client;
  const corps = useMemo(() => ({ contact_ids: choisis, du, au, client: libelleClient }), [choisis, du, au, libelleClient]);

  const changerClient = (v) => { setClient(v); setChoisis([]); setResultat(null); };       // un autre client : on repart de zéro

  const afficher = async () => {
    if (!choisis.length) { toast.error("Cochez au moins un contact."); return; }
    setEnCours(true); toast("Patientez… lecture des conversations en cours");
    try {
      const r = await apiClient.post("/me/liluvine-historique", corps);
      setResultat(r.data);
      toast.success(`${r.data.total} message(s) pour ${r.data.contacts.length} contact(s)${r.data.tronque ? ` — liste limitée aux ${r.data.maximum} plus récents` : ""}.`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Lecture des conversations impossible"); }
    finally { setEnCours(false); }
  };

  // PDF : le serveur compose le document (date et heure, « Liluvine » vertical sur chaque page) ; on l'ouvre dans un onglet pour l'imprimer
  const imprimer = async () => {
    setEnCours(true); toast("Patientez… préparation du PDF en cours");
    try {
      const r = await apiClient.post("/me/liluvine-historique/pdf", corps, { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const fenetre = window.open(url, "_blank");
      if (!fenetre) { const a = document.createElement("a"); a.href = url; a.download = "historique-conversations.pdf"; a.click(); }
      toast.success("PDF prêt : utilisez l'impression de l'onglet qui s'ouvre.");
      setTimeout(() => URL.revokeObjectURL(url), 120000);
    } catch (e) { toast.error("Création du PDF impossible"); }
    finally { setEnCours(false); }
  };
  const exporterCsv = async () => {
    setEnCours(true); toast("Patientez… préparation du fichier CSV en cours");
    try {
      const r = await apiClient.post("/me/liluvine-historique/csv", corps, { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([r.data], { type: "text/csv;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url; a.download = `historique-conversations-${new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "")}.csv`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      toast.success("Fichier CSV exporté.");
    } catch (e) { toast.error("Export CSV impossible"); }
    finally { setEnCours(false); }
  };

  // Tableau : colonnes triables (règle 19) ; ordre initial = date décroissante (déjà fait par le serveur)
  const lignes = useMemo(() => {
    const t = filtre.trim().toLowerCase();
    const l = resultat?.messages || [];
    return t ? l.filter((m) => `${m.contact} ${m.message}`.toLowerCase().includes(t)) : l;
  }, [resultat, filtre]);
  const { lignes: triees, tri, basculer } = useTri(lignes, { quand: (m) => m.quand_iso, contact: (m) => m.contact, sens: (m) => m.sens, message: (m) => m.message });

  return (
    <div className="space-y-5" data-testid="historique-conversations">
      <header>
        <h1 className="flex items-center gap-2 text-2xl font-bold"><History className="h-6 w-6 text-sky-700" /> Historique Conversation</h1>
        <p className="text-sm text-slate-600">Toutes les conversations WhatsApp du Centre de Messagerie, par client et par contacts, de la plus récente à la plus ancienne. Les contacts bloqués sont proposés ; seuls leurs messages écrits pendant le blocage ne sont pas pris en compte.</p>
      </header>

      {/* Lot 467 : chaque bloc se replie / se déplie d'un clic sur son titre */}
      <BlocRepliable id="whatsapp" titre="Conversations WhatsApp — Centre de Messagerie" icone={History} classe="border-slate-200"
        resume={resultat ? `${resultat.total} message(s) · ${resultat.contacts.length} contact(s)` : ""}>
      <section className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block text-sm font-semibold">1. Client
            <select value={client} onChange={(e) => changerClient(e.target.value)} disabled={contacts === null} data-testid="historique-client" className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal">
              <option value="">Choisir un client…</option>
              {clientsOptions.map((o) => <option key={o.label} value={o.valeur}>{o.label}</option>)}
            </select>
          </label>
          <div className="text-sm font-semibold">2. Contacts {client && <span className="font-normal text-slate-500">({contactsDuClient.length})</span>}
            <div className="mt-1">
              <ListeMultiChoix options={optionsContacts} valeur={choisis} onChange={setChoisis} disabled={!client} vide={client ? "Cocher des contacts…" : "Choisissez d'abord un client"} pluriel="contacts choisis" testid="historique-contacts" />
            </div>
          </div>
          <label className="block text-sm font-semibold">Du (facultatif)
            <input type="date" value={du} onChange={(e) => setDu(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" data-testid="historique-du" /></label>
          <label className="block text-sm font-semibold">Au (facultatif)
            <input type="date" value={au} onChange={(e) => setAu(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" data-testid="historique-au" /></label>
        </div>
        <div className="flex flex-wrap items-center gap-2 boutons-distincts">
          <button type="button" onClick={afficher} disabled={enCours || !choisis.length} data-testid="historique-afficher" className="inline-flex items-center gap-1 rounded-full bg-sky-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"><Search className="h-4 w-4" /> Afficher l'historique</button>
          <button type="button" onClick={charger} disabled={enCours} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50"><RefreshCw className="h-4 w-4" /> Actualiser les contacts</button>
        </div>
      </section>

      {resultat && (
        <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="historique-resultat">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-slate-700">
              <b>{resultat.total}</b> message(s) · {resultat.contacts.length} contact(s){resultat.ignores > 0 && <span className="text-amber-700"> · {resultat.ignores} contact(s) ignoré(s) (hors de votre périmètre)</span>}
              {resultat.tronque && <span className="text-amber-700"> · limité aux {resultat.maximum} messages les plus récents : réduisez la période</span>}
              <span className="ml-2 text-xs text-slate-500">édité le {new Date(resultat.genere_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</span>
            </p>
            <div className="flex flex-wrap items-center gap-2 boutons-distincts">
              <button type="button" onClick={imprimer} disabled={enCours} data-testid="historique-pdf" className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1.5 text-sm font-semibold disabled:opacity-50"><Printer className="h-4 w-4" /> Imprimer / PDF</button>
              <button type="button" onClick={exporterCsv} disabled={enCours} data-testid="historique-csv" className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1.5 text-sm font-semibold disabled:opacity-50"><FileSpreadsheet className="h-4 w-4" /> Exporter CSV</button>
            </div>
          </div>
          <label className="flex items-center gap-2 rounded-lg border border-slate-300 px-2 py-1 text-sm sm:w-96"><Search className="h-4 w-4 text-slate-500" />
            <input value={filtre} onChange={(e) => setFiltre(e.target.value)} placeholder="Filtrer par contact ou par texte" className="w-full p-1 outline-none" data-testid="historique-filtre" /></label>
          <div className="max-h-[36rem] overflow-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-sm" data-testid="historique-table">
              <thead className="sticky top-0 bg-slate-50">
                <tr className="text-left text-slate-600">
                  <ThTri cle="quand" tri={tri} onTri={basculer}>Date et heure</ThTri>
                  <ThTri cle="contact" tri={tri} onTri={basculer}>Contact</ThTri>
                  <ThTri cle="sens" tri={tri} onTri={basculer}>Sens</ThTri>
                  <ThTri cle="message" tri={tri} onTri={basculer}>Message</ThTri>
                </tr>
              </thead>
              <tbody>
                {triees.map((m, i) => (
                  <tr key={`${m.id}-${i}`} className="border-t align-top">
                    <td className="whitespace-nowrap p-2 tabular-nums text-slate-700">{m.quand}</td>
                    <td className="p-2"><Pastille nom={m.contact} /></td>
                    <td className="whitespace-nowrap p-2">{m.sens === "Reçu"
                      ? <span className="inline-flex items-center gap-1 text-sky-700"><ArrowDownLeft className="h-4 w-4" /> Reçu</span>
                      : <span className="inline-flex items-center gap-1 text-emerald-700"><ArrowUpRight className="h-4 w-4" /> Envoyé</span>}</td>
                    <td className="whitespace-pre-wrap break-words p-2">{m.message || <span className="italic text-slate-400">(sans texte)</span>}</td>
                  </tr>))}
                {triees.length === 0 && <tr><td colSpan={4} className="p-3 text-slate-500">Aucun message pour cette sélection.</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="flex items-center gap-1 text-[11px] text-slate-500"><FileDown className="h-3 w-3" /> Le PDF et le CSV reprennent toute la sélection (pas seulement le filtre d'écran).</p>
        </section>)}
      </BlocRepliable>

      {/* Lot 467 — bloc À PART, sous les conversations WhatsApp : chat interne du Support Loois avec la durée de l'assistance */}
      <HistoriqueChatInterne clientHaut={client} />
    </div>
  );
}
