/*
 * Lot 292 — Centre de Messagerie → onglet « Suivi des RDV » : on choisit un compte (code client des RDV, ex. CMCO) dans une liste
 * déroulante et on suit, comme dans une discussion, les fils des patients qui ont reçu un rappel de RDV (leurs réponses, la réponse
 * automatique de Liluvine). Lecture seule ; actualisé toutes les 30 secondes. Réservé aux administrateurs et superviseurs.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Bot, Loader2, RefreshCw } from "lucide-react";

const heureCourte = (iso) => { try { return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };
const LIBELLES_JOURS = { 1: "Dernières 24 h", 3: "3 derniers jours", 7: "7 derniers jours", 14: "14 derniers jours", 30: "30 derniers jours" };

export default function SuiviRdv() {
  const [comptes, setComptes] = useState([]);
  const [joursChoix, setJoursChoix] = useState([1, 3, 7, 14, 30]);
  const [code, setCode] = useState("");              // "" = tous les comptes
  const [jours, setJours] = useState(7);
  const [fils, setFils] = useState(null);
  const [choisi, setChoisi] = useState(null);        // fil ouvert (objet de la liste)
  const [messages, setMessages] = useState(null);
  const [synchro, setSynchro] = useState(false);
  const bas = useRef(null);

  useEffect(() => {
    apiClient.get("/admin/planning/suivi/comptes")
      .then((r) => { setComptes(r.data?.comptes || []); if (r.data?.jours_choix) setJoursChoix(r.data.jours_choix); })
      .catch((e) => toast.error(e?.response?.data?.detail || "Comptes indisponibles"));
  }, []);

  const chargerFils = useCallback(async () => {
    setSynchro(true);
    try {
      const r = await apiClient.get("/admin/planning/suivi/fils", { params: { code, jours } });
      setFils(r.data?.fils || []);
    } catch (e) { toast.error(e?.response?.data?.detail || "Suivi indisponible"); }
    finally { setSynchro(false); }
  }, [code, jours]);

  const chargerFil = useCallback(async () => {
    if (!choisi) return;
    try {
      const r = await apiClient.get("/admin/planning/suivi/fil", { params: { telephone: choisi.telephone, jours } });
      setMessages(r.data?.messages || []);
    } catch (e) { toast.error(e?.response?.data?.detail || "Conversation indisponible"); }
  }, [choisi, jours]);

  useEffect(() => { setChoisi(null); setMessages(null); chargerFils(); }, [chargerFils]);
  useEffect(() => { setMessages(null); chargerFil(); }, [chargerFil]);
  // Actualisation automatique toutes les 30 s (liste et fil ouvert)
  useEffect(() => {
    const t = setInterval(() => { chargerFils(); chargerFil(); }, 30000);
    return () => clearInterval(t);
  }, [chargerFils, chargerFil]);
  useEffect(() => { bas.current?.scrollIntoView({ block: "end" }); }, [messages]);

  return (
    <div className="space-y-3" data-testid="suivi-rdv">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-slate-600">Compte
          <select value={code} onChange={(e) => setCode(e.target.value)} data-testid="suivi-compte"
                  className="mt-1 block px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono min-w-[12rem]">
            <option value="">Tous les comptes</option>
            {comptes.map((c) => <option key={c.code} value={c.code}>{c.code} ({c.rappels} rappel{c.rappels > 1 ? "s" : ""})</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-600">Période
          <select value={jours} onChange={(e) => setJours(Number(e.target.value))} data-testid="suivi-jours"
                  className="mt-1 block px-3 py-2 border border-slate-300 rounded-lg text-sm">
            {joursChoix.map((j) => <option key={j} value={j}>{LIBELLES_JOURS[j] || `${j} jours`}</option>)}
          </select>
        </label>
        <button type="button" onClick={() => { chargerFils(); chargerFil(); }} disabled={synchro} title="Actualiser"
                className="p-2 rounded-lg border border-slate-300 hover:bg-slate-50 disabled:opacity-60" data-testid="suivi-actualiser">
          <RefreshCw className={`h-4 w-4 text-indigo-600 ${synchro ? "animate-spin" : ""}`} />
        </button>
        <span className="text-xs text-slate-500 pb-2">{fils ? `${fils.length} patient${fils.length > 1 ? "s" : ""} rappelé${fils.length > 1 ? "s" : ""}` : ""}</span>
      </div>

      <div className="grid md:grid-cols-[22rem_1fr] gap-3">
        {/* Liste des fils */}
        <div className="rounded-xl border border-slate-200 bg-white max-h-[65vh] overflow-y-auto" data-testid="suivi-fils">
          {!fils ? <div className="p-4"><Loader2 className="h-5 w-5 animate-spin text-slate-400 mx-auto" /></div>
            : fils.length === 0 ? <p className="p-4 text-sm text-slate-500">Aucun rappel envoyé sur cette période pour ce compte.</p>
            : fils.map((f) => (
              <button key={f.cle} type="button" onClick={() => setChoisi(f)}
                      className={`w-full text-left px-3 py-2 border-b border-slate-100 hover:bg-sky-50 ${choisi?.cle === f.cle ? "bg-indigo-50" : ""}`} data-testid="suivi-fil-ligne">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-sm truncate">{f.patient || f.telephone}</span>
                  <span className="text-[10px] text-slate-400 shrink-0">{heureCourte(f.dernier?.date || f.rappel_le)}</span>
                </div>
                <div className="text-[11px] text-slate-500 truncate">{f.code} · {f.medecin || "—"} · RDV {heureCourte(f.rdv)}</div>
                <div className="text-xs text-slate-600 truncate">{f.dernier ? `${f.dernier.sens === "entrant" ? "↘" : "↗"} ${f.dernier.texte}` : "Aucun message"}</div>
                <div className="flex gap-1 mt-1 flex-wrap">
                  {f.demande_report && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">Report demandé</span>}
                  {f.reponse_auto_le && <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-100 text-violet-800">Réponse auto</span>}
                  {f.a_repondu && !f.demande_report && <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-100 text-sky-800">A répondu</span>}
                  {f.rappel_statut === "failed" && <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-100 text-rose-800">Rappel non remis</span>}
                </div>
              </button>
            ))}
        </div>

        {/* Fil ouvert, présenté comme une discussion */}
        <div className="rounded-xl border border-slate-200 bg-slate-50 max-h-[65vh] overflow-y-auto p-3 space-y-2" data-testid="suivi-conversation">
          {!choisi ? <p className="text-sm text-slate-500 text-center py-10">Choisissez un patient pour suivre sa conversation.</p> : (
            <>
              <div className="text-xs text-slate-500 pb-1 border-b border-slate-200">
                <b className="text-slate-700">{choisi.patient}</b> · {choisi.telephone} · {choisi.medecin || "—"} · RDV {heureCourte(choisi.rdv)}
              </div>
              {!messages ? <Loader2 className="h-5 w-5 animate-spin text-slate-400 mx-auto" /> : messages.map((m) => (
                <div key={m.id} className={`flex ${m.sens === "sortant" ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm shadow-sm ${m.sens === "sortant" ? "bg-indigo-600 text-white" : "bg-white ring-1 ring-slate-200 text-slate-800"}`}>
                    <div className="whitespace-pre-wrap break-words">{m.texte}</div>
                    <div className={`mt-1 flex items-center gap-1 text-[10px] ${m.sens === "sortant" ? "text-indigo-100" : "text-slate-400"}`}>
                      {m.liluvine && <Bot className="h-3 w-3" title="Envoyé automatiquement par Liluvine" />}
                      {heureCourte(m.date)}{m.statut ? ` · ${m.statut}` : ""}
                    </div>
                  </div>
                </div>
              ))}
              <div ref={bas} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
