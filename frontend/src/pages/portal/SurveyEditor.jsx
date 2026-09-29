/*
  SurveyEditor — lot 27 : conception d'un sondage WhatsApp.

  - Titre, texte d'introduction, message de remerciement, date limite ;
  - questions : choix unique, choix multiples, oui/non, note de 1 à 5,
    recommandation de 0 à 10 (score NPS), réponse libre ;
    chaque question peut être obligatoire, déplacée (▲ ▼), dupliquée, supprimée ;
    lot 41 : l'ordre des questions se change aussi par glisser-déposer (poignée ⠿) ou en
    choisissant directement sa position (« 3 / 8 ») ; l'ordre des choix d'une question
    aussi (▲ ▼). Les réponses déjà reçues restent rattachées à leur question (identifiant) ;
  - « Résultats anonymes » : les noms des répondants ne sont pas affichés ;
  - message WhatsApp proposé à l'envoi ({{name}}, {{sondage}}, {{lien}}) ;
  - aperçu à droite, tel que le destinataire le verra sur son téléphone.
  Route : /portal/surveys/:sid/edit (« new » pour un nouveau sondage).
*/
import React, { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { ArrowLeft, Plus, Trash2, Copy, ChevronUp, ChevronDown, GripVertical, Save, Star, X } from "lucide-react";

// Types de questions proposés (même liste que le serveur)
const TYPES = [
  ["single", "Choix unique"], ["multi", "Choix multiples"], ["yesno", "Oui / Non"],
  ["rating", "Note de 1 à 5"], ["nps", "Recommandation (0 à 10)"], ["text", "Réponse libre"],
];
const DEFAULT_MESSAGE = "Bonjour {{name}}, votre avis compte pour nous ! Merci de répondre à notre court sondage « {{sondage}} » : {{lien}}";

// Identifiant local d'une nouvelle question (le serveur garde celui-ci)
const newId = () => Math.random().toString(36).slice(2, 10);
const blankQuestion = (type = "single") => ({
  id: newId(), type, label: "", required: true, help: "",
  options: type === "single" || type === "multi" ? ["", ""] : [],
});

export default function SurveyEditor() {
  const { sid } = useParams();
  const isNew = sid === "new";
  const { pathname } = useLocation();
  const base = pathname.startsWith("/admin") ? "/admin" : "/portal";
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superviseur";
  const [roster, setRoster] = useState([]);           // clients (admin : sondage créé pour un client)
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [answeredCount, setAnsweredCount] = useState(0);
  const [s, setS] = useState({
    title: "", description: "", thank_you: "Merci pour vos réponses !", status: "draft",
    anonymous: false, closes_at: "", message_text: DEFAULT_MESSAGE, questions: [blankQuestion()],
  });

  // Admin / Superviseur : liste des clients pour choisir le propriétaire du sondage
  useEffect(() => {
    if (isAdmin) apiClient.get("/me/clients-roster").then((r) => setRoster(Array.isArray(r.data) ? r.data : [])).catch(() => {});
  }, [isAdmin]);

  // Chargement d'un sondage existant
  useEffect(() => {
    if (isNew) return;
    apiClient.get(`/me/wa-surveys/${sid}`)
      .then((r) => {
        const d = r.data;
        setS({ ...d, closes_at: (d.closes_at || "").slice(0, 10), message_text: d.message_text || DEFAULT_MESSAGE,
          questions: (d.questions || []).map((q) => ({ ...q, help: q.help || "" })) });
        setAnsweredCount(d.answered_count || 0);
      })
      .catch((e) => toast.error(e?.response?.data?.detail || "Sondage introuvable"))
      .finally(() => setLoading(false));
  }, [sid, isNew]);

  const set = (patch) => setS((prev) => ({ ...prev, ...patch }));
  const setQ = (i, patch) => setS((prev) => ({
    ...prev, questions: prev.questions.map((q, k) => (k === i ? { ...q, ...patch } : q)),
  }));
  const moveQ = (i, dir) => setS((prev) => {
    const qs = [...prev.questions];
    const j = i + dir;
    if (j < 0 || j >= qs.length) return prev;
    [qs[i], qs[j]] = [qs[j], qs[i]];
    return { ...prev, questions: qs };
  });
  // Lot 41 — déplace la question de la position `de` à la position `vers` (glisser-déposer
  // ou choix direct de la position) ; les autres questions se décalent.
  const placerQ = (de, vers) => setS((prev) => {
    if (de === vers || vers < 0 || vers >= prev.questions.length) return prev;
    const qs = [...prev.questions];
    const [q] = qs.splice(de, 1);
    qs.splice(vers, 0, q);
    return { ...prev, questions: qs };
  });
  const [glisse, setGlisse] = useState(null);        // index de la question en cours de glisser-déposer
  const [survol, setSurvol] = useState(null);        // index de la question survolée (repère visuel)
  // Lot 41 — ordre des choix d'une question (▲ ▼)
  const moveOpt = (i, k, dir) => {
    const opts = [...s.questions[i].options];
    const j = k + dir;
    if (j < 0 || j >= opts.length) return;
    [opts[k], opts[j]] = [opts[j], opts[k]];
    setQ(i, { options: opts });
  };
  const changeType = (i, type) => {
    const q = s.questions[i];
    // Passage vers un type à choix : on garde les choix existants, sinon 2 choix vides
    const options = type === "single" || type === "multi" ? (q.options?.length ? q.options : ["", ""]) : [];
    setQ(i, { type, options });
  };

  const save = async (nextStatus) => {
    const payload = {
      ...s,
      status: nextStatus || s.status,
      closes_at: s.closes_at ? `${s.closes_at}T23:59:59` : null,
      questions: s.questions.map((q) => ({ ...q, options: (q.options || []).filter((o) => o.trim()) })),
    };
    setSaving(true);
    try {
      const r = isNew ? await apiClient.post("/me/wa-surveys", payload) : await apiClient.put(`/me/wa-surveys/${sid}`, payload);
      toast.success(nextStatus === "active" ? "Sondage enregistré et ouvert" : "Sondage enregistré");
      if (isNew) navigate(`${base}/surveys/${r.data.id}/edit`, { replace: true });
      else set({ status: r.data.status });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Enregistrement impossible");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="text-sm text-slate-500">Chargement…</p>;

  const input = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-sawali-blue focus:outline-none";
  return (
    <div className="max-w-6xl space-y-5" data-testid="survey-editor">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to={`${base}/surveys`} className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900">
          <ArrowLeft className="h-4 w-4" /> Sondages
        </Link>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => save()} disabled={saving} data-testid="survey-save"
            className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50">
            <Save className="h-4 w-4" /> Enregistrer
          </button>
          {s.status !== "active" && (
            <button onClick={() => save("active")} disabled={saving} data-testid="survey-open"
              className="rounded-lg bg-emerald-600 text-white px-3 py-2 text-sm hover:bg-emerald-700 disabled:opacity-50">
              Enregistrer et ouvrir
            </button>
          )}
          {s.status === "active" && !isNew && (
            <button onClick={() => { if (window.confirm("Clôturer ce sondage ? Les réponses ne seront plus acceptées.")) save("closed"); }}
              disabled={saving} data-testid="survey-close"
              className="rounded-lg bg-rose-600 text-white px-3 py-2 text-sm hover:bg-rose-700 disabled:opacity-50">
              Clôturer
            </button>
          )}
        </div>
      </div>

      {answeredCount > 0 && (
        <p className="rounded-lg bg-amber-50 ring-1 ring-amber-200 px-3 py-2 text-xs text-amber-800">
          Ce sondage a déjà {answeredCount} réponse(s). Modifier l'intitulé d'une question garde ses réponses ;
          supprimer une question ou un choix retire ces réponses des statistiques.
        </p>
      )}

      <div className="grid lg:grid-cols-[1fr_320px] gap-5">
        <div className="space-y-4">
          {/* En-tête du sondage */}
          <div className="rounded-xl bg-white ring-1 ring-slate-200 p-4 space-y-3">
            <input value={s.title} onChange={(e) => set({ title: e.target.value })} placeholder="Titre du sondage (ex. Satisfaction logiciels 2026)"
              className={`${input} text-lg font-semibold`} data-testid="survey-title" maxLength={200} />
            <textarea value={s.description} onChange={(e) => set({ description: e.target.value })} rows={2}
              placeholder="Introduction affichée au destinataire (facultatif)" className={input} maxLength={2000} />
            <div className="grid sm:grid-cols-2 gap-3">
              <label className="text-xs text-slate-600">Message de remerciement
                <input value={s.thank_you} onChange={(e) => set({ thank_you: e.target.value })} className={`${input} mt-1`} maxLength={1000} />
              </label>
              <label className="text-xs text-slate-600">Date limite de réponse (facultative)
                <input type="date" value={s.closes_at || ""} onChange={(e) => set({ closes_at: e.target.value })} className={`${input} mt-1`} />
              </label>
            </div>
            {isAdmin && (
              <label className="block text-xs text-slate-600">Client propriétaire (il voit le sondage et il lui est facturé)
                <select value={s.client_id || ""} onChange={(e) => set({ client_id: e.target.value || null })} className={`${input} mt-1`} data-testid="survey-client">
                  <option value="">{isNew ? "Mon compte" : "— inchangé —"}</option>
                  {roster.map((c) => <option key={c.id} value={c.id}>{c.company || c.full_name}{c.client_code ? ` · ${c.client_code}` : ""}</option>)}
                </select>
              </label>
            )}
            <label className="inline-flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={!!s.anonymous} onChange={(e) => set({ anonymous: e.target.checked })} data-testid="survey-anonymous" />
              Résultats anonymes (les noms des répondants ne sont pas affichés)
            </label>
          </div>

          {/* Questions */}
          {s.questions.map((q, i) => (
            <div key={q.id} data-testid={`survey-q-${i}`}
              onDragOver={(e) => { if (glisse !== null) { e.preventDefault(); setSurvol(i); } }}
              onDrop={(e) => { e.preventDefault(); if (glisse !== null) placerQ(glisse, i); setGlisse(null); setSurvol(null); }}
              className={`rounded-xl bg-white ring-1 p-4 space-y-3 transition ${glisse === i ? "opacity-50" : ""} ${
                survol === i && glisse !== null && glisse !== i ? "ring-2 ring-sawali-blue" : "ring-slate-200"}`}>
              <div className="flex flex-wrap items-center gap-2">
                {/* Lot 41 — poignée de glisser-déposer */}
                <span draggable onDragStart={(e) => { setGlisse(i); e.dataTransfer.effectAllowed = "move"; }}
                  onDragEnd={() => { setGlisse(null); setSurvol(null); }} title="Glisser pour déplacer la question"
                  className="cursor-grab active:cursor-grabbing text-slate-400 hover:text-slate-700" data-testid={`survey-q-drag-${i}`}>
                  <GripVertical className="h-5 w-5" />
                </span>
                <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-sawali-blue text-white text-xs font-bold">{i + 1}</span>
                {/* Lot 41 — position choisie directement */}
                <select value={i} onChange={(e) => placerQ(i, Number(e.target.value))} title="Position de la question"
                  className="rounded-lg border border-slate-300 px-1.5 py-1 text-xs" data-testid={`survey-q-pos-${i}`}>
                  {s.questions.map((_, n) => <option key={n} value={n}>{n + 1} / {s.questions.length}</option>)}
                </select>
                <select value={q.type} onChange={(e) => changeType(i, e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                  data-testid={`survey-q-type-${i}`}>
                  {TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
                <label className="inline-flex items-center gap-1 text-xs text-slate-600">
                  <input type="checkbox" checked={q.required} onChange={(e) => setQ(i, { required: e.target.checked })} /> Obligatoire
                </label>
                <div className="ml-auto flex items-center gap-1">
                  <button onClick={() => moveQ(i, -1)} disabled={i === 0} title="Monter" className="p-1.5 rounded hover:bg-slate-100 disabled:opacity-30"><ChevronUp className="h-4 w-4" /></button>
                  <button onClick={() => moveQ(i, 1)} disabled={i === s.questions.length - 1} title="Descendre" className="p-1.5 rounded hover:bg-slate-100 disabled:opacity-30"><ChevronDown className="h-4 w-4" /></button>
                  <button onClick={() => set({ questions: [...s.questions.slice(0, i + 1), { ...q, id: newId() }, ...s.questions.slice(i + 1)] })}
                    title="Dupliquer" className="p-1.5 rounded hover:bg-slate-100"><Copy className="h-4 w-4" /></button>
                  <button onClick={() => set({ questions: s.questions.filter((_, k) => k !== i) })} title="Supprimer"
                    className="p-1.5 rounded text-rose-600 hover:bg-rose-50"><Trash2 className="h-4 w-4" /></button>
                </div>
              </div>
              <input value={q.label} onChange={(e) => setQ(i, { label: e.target.value })} placeholder="Intitulé de la question"
                className={`${input} font-medium`} data-testid={`survey-q-label-${i}`} maxLength={500} />
              <input value={q.help || ""} onChange={(e) => setQ(i, { help: e.target.value })} placeholder="Précision sous la question (facultatif)"
                className={`${input} text-xs`} maxLength={300} />
              {(q.type === "single" || q.type === "multi") && (
                <div className="space-y-1.5">
                  {q.options.map((o, k) => (
                    <div key={k} className="flex items-center gap-2">
                      <span className={`h-4 w-4 shrink-0 ring-2 ring-slate-300 ${q.type === "single" ? "rounded-full" : "rounded"}`} />
                      <input value={o} onChange={(e) => setQ(i, { options: q.options.map((x, n) => (n === k ? e.target.value : x)) })}
                        placeholder={`Choix ${k + 1}`} className={input} data-testid={`survey-q-${i}-opt-${k}`} maxLength={200} />
                      <button onClick={() => moveOpt(i, k, -1)} disabled={k === 0} title="Monter ce choix"
                        className="p-1 text-slate-400 hover:text-slate-700 disabled:opacity-30"><ChevronUp className="h-4 w-4" /></button>
                      <button onClick={() => moveOpt(i, k, 1)} disabled={k === q.options.length - 1} title="Descendre ce choix"
                        className="p-1 text-slate-400 hover:text-slate-700 disabled:opacity-30"><ChevronDown className="h-4 w-4" /></button>
                      <button onClick={() => setQ(i, { options: q.options.filter((_, n) => n !== k) })} disabled={q.options.length <= 2}
                        className="p-1 text-slate-400 hover:text-rose-600 disabled:opacity-30" title="Retirer ce choix"><X className="h-4 w-4" /></button>
                    </div>
                  ))}
                  {q.options.length < 20 && (
                    <button onClick={() => setQ(i, { options: [...q.options, ""] })} className="text-xs text-sawali-blue hover:underline"
                      data-testid={`survey-q-${i}-add-opt`}>
                      + Ajouter un choix
                    </button>
                  )}
                </div>
              )}
              {q.type === "rating" && <p className="text-xs text-slate-500 flex items-center gap-1">Le destinataire choisit de 1 à 5 <Star className="h-3.5 w-3.5 text-amber-400 fill-amber-400" /></p>}
              {q.type === "nps" && <p className="text-xs text-slate-500">Échelle de 0 à 10. Score NPS = % de notes 9-10 − % de notes 0-6.</p>}
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            {TYPES.map(([k, l]) => (
              <button key={k} onClick={() => set({ questions: [...s.questions, blankQuestion(k)] })} data-testid={`survey-add-${k}`}
                className="inline-flex items-center gap-1 rounded-lg border border-dashed border-slate-300 bg-white px-3 py-1.5 text-xs hover:border-sawali-blue hover:text-sawali-blue">
                <Plus className="h-3.5 w-3.5" /> {l}
              </button>
            ))}
          </div>

          {/* Message WhatsApp proposé */}
          <div className="rounded-xl bg-white ring-1 ring-slate-200 p-4 space-y-2">
            <p className="text-sm font-semibold text-slate-800">Message WhatsApp (contacts qui vous ont écrit dans les dernières 24 h)</p>
            <textarea value={s.message_text} onChange={(e) => set({ message_text: e.target.value })} rows={3} className={input} maxLength={1000} />
            <p className="text-[11px] text-slate-500">
              Variables : <code>{"{{name}}"}</code> nom du contact, <code>{"{{sondage}}"}</code> titre, <code>{"{{lien}}"}</code> lien personnel.
              Pour les autres contacts, l'envoi utilise un modèle Meta approuvé (choisi au moment de l'envoi).
            </p>
          </div>
        </div>

        {/* Aperçu « téléphone » */}
        <div className="lg:sticky lg:top-4 self-start">
          <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Aperçu destinataire</p>
          <div className="rounded-[2rem] bg-slate-900 p-3 shadow-xl">
            <div className="rounded-[1.5rem] bg-slate-50 p-4 max-h-[70vh] overflow-auto space-y-3">
              <p className="font-bold text-slate-900">{s.title || "Titre du sondage"}</p>
              {s.description && <p className="text-xs text-slate-600 whitespace-pre-line">{s.description}</p>}
              {s.questions.map((q, i) => (
                <div key={q.id} className="rounded-lg bg-white p-2.5 ring-1 ring-slate-200">
                  <p className="text-xs font-semibold text-slate-800">{i + 1}. {q.label || "…"}{q.required && <span className="text-rose-500"> *</span>}</p>
                  {(q.type === "single" || q.type === "multi") && q.options.filter((o) => o.trim()).map((o) => (
                    <p key={o} className="mt-1 text-[11px] text-slate-600 flex items-center gap-1.5">
                      <span className={`h-3 w-3 ring-1 ring-slate-400 ${q.type === "single" ? "rounded-full" : "rounded-sm"}`} /> {o}
                    </p>
                  ))}
                  {q.type === "yesno" && <p className="mt-1 text-[11px] text-slate-600">[ Oui ]  [ Non ]</p>}
                  {q.type === "rating" && <p className="mt-1 text-amber-400">★★★★★</p>}
                  {q.type === "nps" && <p className="mt-1 text-[10px] text-slate-500">0 1 2 3 4 5 6 7 8 9 10</p>}
                  {q.type === "text" && <div className="mt-1 h-6 rounded bg-slate-100" />}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
