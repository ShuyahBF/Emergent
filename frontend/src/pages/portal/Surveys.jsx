/*
  Surveys — lot 27 : portefeuille des sondages WhatsApp.

  Liste des sondages du compte avec leurs chiffres (envoyés, ouverts,
  réponses, taux de réponse). Depuis chaque carte :
    - Envoyer : choix des destinataires (tous les contacts d'un client, groupes,
      contacts, échantillon aléatoire) puis envoi par WhatsApp ;
    - Résultats : taux, graphiques par question, relance, export Excel ;
    - Éditer, Dupliquer, Supprimer.
*/
import React, { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { BarChart3, FileUp, Plus, Edit, Trash2, Copy, Send, Search, Users, Eye, CheckCircle2, Trophy } from "lucide-react";
import FormsSurveysTabs from "@/components/FormsSurveysTabs";
import SurveySendModal from "@/components/SurveySendModal";
import SurveyContributors from "@/components/SurveyContributors";
import ImportDocumentModal from "@/components/ImportDocumentModal";

// Statut -> [libellé, classes du badge]
export const SURVEY_STATUS = {
  draft: ["Brouillon", "bg-slate-100 text-slate-600"],
  active: ["Ouvert", "bg-emerald-100 text-emerald-700"],
  closed: ["Clôturé", "bg-rose-100 text-rose-700"],
};

export default function Surveys() {
  const { pathname } = useLocation();
  const base = pathname.startsWith("/admin") ? "/admin" : "/portal";
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [sendFor, setSendFor] = useState(null);     // sondage à envoyer (fenêtre d'envoi)
  const [view, setView] = useState("surveys");      // surveys | contributors
  const [importOpen, setImportOpen] = useState(false); // lot 33 : « Créer depuis un document »

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/wa-surveys");
      setItems(r.data?.items || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible de charger les sondages");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  // Filtre texte + statut
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((s) => (status === "all" || s.status === status)
      && (!q || (s.title || "").toLowerCase().includes(q) || (s.description || "").toLowerCase().includes(q)));
  }, [items, search, status]);

  // Totaux du portefeuille (bandeau du haut)
  const totals = useMemo(() => items.reduce((a, s) => ({
    surveys: a.surveys + 1,
    sent: a.sent + (s.stats?.sent || 0),
    answered: a.answered + (s.stats?.answered || 0),
  }), { surveys: 0, sent: 0, answered: 0 }), [items]);

  const duplicate = async (s) => {
    try {
      const r = await apiClient.post(`/me/wa-surveys/${s.id}/duplicate`);
      toast.success("Copie créée (brouillon)");
      navigate(`${base}/surveys/${r.data.id}/edit`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  const remove = async (s) => {
    if (!window.confirm(`Supprimer le sondage « ${s.title} » avec toutes ses réponses ?`)) return;
    try { await apiClient.delete(`/me/wa-surveys/${s.id}`); toast.success("Sondage supprimé"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  return (
    <div className="max-w-6xl space-y-6" data-testid="surveys-page">
      <FormsSurveysTabs active="surveys" />
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Formulaires &amp; Sondages</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-sawali-blue" /> Sondages WhatsApp
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Chaque destinataire reçoit sur WhatsApp un lien personnel : vous savez qui a ouvert et qui a répondu.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
        <button onClick={() => setImportOpen(true)} data-testid="survey-import-doc-btn"
          className="inline-flex items-center gap-2 rounded-lg ring-1 ring-sawali-blue/40 text-sawali-blue px-4 py-2 text-sm hover:bg-sawali-blue/5">
          <FileUp className="h-4 w-4" /> Créer depuis un document
        </button>
        <Link to={`${base}/surveys/new/edit`} data-testid="survey-create-btn"
          className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light">
          <Plus className="h-4 w-4" /> Nouveau sondage
        </Link>
        </div>
      </div>

      {/* Vue : liste des sondages ou meilleurs contributeurs */}
      <div className="flex gap-2 border-b border-slate-200">
        {[["surveys", "Mes sondages", BarChart3], ["contributors", "Meilleurs contributeurs", Trophy]].map(([k, l, Icon]) => (
          <button key={k} onClick={() => setView(k)} data-testid={`surveys-view-${k}`}
            className={`inline-flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 transition ${view === k ? "border-sawali-blue text-sawali-blue font-semibold" : "border-transparent text-slate-500 hover:text-slate-900"}`}>
            <Icon className="h-4 w-4" /> {l}
          </button>
        ))}
      </div>

      {importOpen && (
        <ImportDocumentModal cible="sondage" lienEditeur={(id) => `${base}/surveys/${id}/edit`}
          onClose={() => { setImportOpen(false); load(); }} />
      )}

      {view === "contributors" ? <SurveyContributors /> : (<>
      {/* Chiffres du portefeuille */}
      <div className="grid grid-cols-3 gap-3">
        {[["Sondages", totals.surveys, "text-sawali-blue"], ["Messages envoyés", totals.sent, "text-sky-600"],
          ["Réponses reçues", totals.answered, "text-emerald-600"]].map(([l, v, c]) => (
          <div key={l} className="rounded-xl bg-white ring-1 ring-slate-200 p-3">
            <p className="text-[11px] uppercase tracking-wider text-slate-500">{l}</p>
            <p className={`text-2xl font-bold tabular-nums ${c}`}>{v}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[12rem] max-w-sm">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Rechercher un sondage"
            className="w-full rounded-lg border border-slate-300 pl-8 pr-3 py-2 text-sm" data-testid="survey-search" />
        </div>
        {[["all", "Tous"], ["draft", "Brouillons"], ["active", "Ouverts"], ["closed", "Clôturés"]].map(([k, l]) => (
          <button key={k} onClick={() => setStatus(k)} data-testid={`survey-filter-${k}`}
            className={`text-xs px-3 py-1.5 rounded-full ring-1 ${status === k ? "bg-sawali-blue text-white ring-sawali-blue" : "bg-white ring-slate-200 hover:ring-sawali-blue/50"}`}>
            {l}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : shown.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-slate-200 p-10 text-center text-slate-500" data-testid="surveys-empty">
          <BarChart3 className="h-10 w-10 mx-auto text-slate-300" />
          <p className="mt-2 text-sm">{items.length ? "Aucun sondage ne correspond." : "Aucun sondage pour l'instant."}</p>
          {!items.length && (
            <Link to={`${base}/surveys/new/edit`} className="mt-3 inline-flex items-center gap-1 text-sm text-sawali-blue hover:underline">
              <Plus className="h-4 w-4" /> Créer le premier sondage
            </Link>
          )}
        </div>
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {shown.map((s) => {
            const [stLabel, stCls] = SURVEY_STATUS[s.status] || SURVEY_STATUS.draft;
            const st = s.stats || {};
            return (
              <div key={s.id} className="rounded-xl bg-white ring-1 ring-slate-200 p-4 flex flex-col gap-3" data-testid={`survey-card-${s.id}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="font-semibold text-slate-900 truncate">{s.title}</h3>
                    <p className="text-xs text-slate-500">
                      {s.questions_count} question(s) · créé par {s.created_by_label || "—"}
                      {s.client_name && <> · client <b className="text-slate-700">{s.client_name}</b></>}
                    </p>
                  </div>
                  <span className={`shrink-0 text-[11px] font-medium rounded-full px-2 py-0.5 ${stCls}`}>{stLabel}</span>
                </div>
                {/* Chiffres clés du sondage */}
                <div className="grid grid-cols-4 gap-2 text-center">
                  {[[Users, "Envoyés", st.sent || 0], [Eye, "Ouverts", st.opened || 0],
                    [CheckCircle2, "Réponses", st.answered || 0],
                    [BarChart3, "Taux", st.response_rate == null ? "—" : `${st.response_rate} %`]].map(([Icon, l, v]) => (
                    <div key={l} className="rounded-lg bg-slate-50 py-1.5">
                      <Icon className="h-3.5 w-3.5 mx-auto text-slate-400" />
                      <p className="text-sm font-bold tabular-nums text-slate-800">{v}</p>
                      <p className="text-[10px] text-slate-500">{l}</p>
                    </div>
                  ))}
                </div>
                {/* Barre du taux de réponse */}
                <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
                  <div className="h-full bg-emerald-500" style={{ width: `${Math.min(100, st.response_rate || 0)}%` }} />
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <button onClick={() => setSendFor(s)} disabled={s.status === "closed" || !s.questions_count}
                    title={s.status === "closed" ? "Sondage clôturé" : "Envoyer par WhatsApp"} data-testid={`survey-send-${s.id}`}
                    className="inline-flex items-center gap-1 text-[11px] rounded bg-emerald-600 text-white px-2.5 py-1.5 hover:bg-emerald-700 disabled:opacity-40">
                    <Send className="h-3.5 w-3.5" /> Envoyer
                  </button>
                  <Link to={`${base}/surveys/${s.id}/results`} data-testid={`survey-results-${s.id}`}
                    className="inline-flex items-center gap-1 text-[11px] rounded bg-indigo-600 text-white px-2.5 py-1.5 hover:bg-indigo-700">
                    <BarChart3 className="h-3.5 w-3.5" /> Résultats
                  </Link>
                  <Link to={`${base}/surveys/${s.id}/edit`} data-testid={`survey-edit-${s.id}`}
                    className="inline-flex items-center gap-1 text-[11px] rounded bg-slate-900 text-white px-2.5 py-1.5 hover:bg-slate-800">
                    <Edit className="h-3.5 w-3.5" /> Éditer
                  </Link>
                  <button onClick={() => duplicate(s)} className="inline-flex items-center gap-1 text-[11px] rounded ring-1 ring-slate-300 px-2.5 py-1.5 hover:bg-slate-50">
                    <Copy className="h-3.5 w-3.5" /> Dupliquer
                  </button>
                  <button onClick={() => remove(s)} className="inline-flex items-center gap-1 text-[11px] rounded ring-1 ring-rose-200 text-rose-600 px-2.5 py-1.5 hover:bg-rose-50">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
      </>)}
      {sendFor && (
        <SurveySendModal survey={sendFor} onClose={() => setSendFor(null)}
          onSent={() => { setSendFor(null); navigate(`${base}/surveys/${sendFor.id}/results`); }} />
      )}
    </div>
  );
}
