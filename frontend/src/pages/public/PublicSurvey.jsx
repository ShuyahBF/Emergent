/*
  PublicSurvey — lot 27 : page de réponse à un sondage WhatsApp (/s/:token).

  Ouverte depuis le lien personnel reçu sur WhatsApp, sans compte ni mot de
  passe. Pensée pour le téléphone : grands boutons, étoiles, échelle 0-10.
  - « Bonjour Awa » quand le sondage n'est pas anonyme ;
  - les questions obligatoires sont signalées et contrôlées avant l'envoi ;
  - déjà répondu : les réponses sont reprises et peuvent être corrigées
    tant que le sondage est ouvert ;
  - sondage clôturé ou date limite passée : message clair.
*/
import React, { useEffect, useState } from "react";
import axios from "axios";
import { useParams } from "react-router-dom";
import { CheckCircle2, Star, Send, Loader2, Lock } from "lucide-react";
import { LOGO_URL } from "@/lib/brand";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function PublicSurvey() {
  const { token } = useParams();
  const [s, setS] = useState(null);
  const [error, setError] = useState("");
  const [answers, setAnswers] = useState({});
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState("");
  const [missing, setMissing] = useState(null);     // id de la 1re question sans réponse

  useEffect(() => {
    axios.get(`${API}/public/surveys/${token}`)
      .then((r) => { setS(r.data); setAnswers(r.data.answers || {}); })
      .catch((e) => setError(e?.response?.data?.detail || "Lien de sondage invalide"));
  }, [token]);

  const set = (qid, v) => { setAnswers((a) => ({ ...a, [qid]: v })); if (missing === qid) setMissing(null); };
  const toggleMulti = (qid, opt) => {
    const cur = answers[qid] || [];
    set(qid, cur.includes(opt) ? cur.filter((x) => x !== opt) : [...cur, opt]);
  };

  const submit = async () => {
    // Contrôle des questions obligatoires avant l'envoi
    const isEmpty = (v) => v === undefined || v === null || (typeof v === "string" && !v.trim()) || (Array.isArray(v) && !v.length);
    const first = s.questions.find((q) => q.required && isEmpty(answers[q.id]));
    if (first) {
      setMissing(first.id);
      document.getElementById(`q-${first.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    setSending(true);
    try {
      const r = await axios.post(`${API}/public/surveys/${token}`, { answers });
      setDone(r.data?.thank_you || "Merci pour vos réponses !");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError(e?.response?.data?.detail || "Envoi impossible, réessayez");
    } finally {
      setSending(false);
    }
  };

  const shell = (children) => (
    <div className="min-h-screen bg-gradient-to-b from-emerald-50 to-slate-50 px-4 py-6">
      <div className="mx-auto max-w-xl">
        <img src={LOGO_URL} alt="" className="h-8 mb-4 opacity-80" />
        {children}
      </div>
    </div>
  );

  if (error && !s) return shell(<div className="rounded-2xl bg-white p-6 shadow text-center text-slate-700" data-testid="survey-error">{error}</div>);
  if (!s) return shell(<p className="text-slate-500 text-sm">Chargement…</p>);
  if (done) {
    return shell(
      <div className="rounded-2xl bg-white p-8 shadow text-center" data-testid="survey-done">
        <CheckCircle2 className="h-14 w-14 mx-auto text-emerald-500" />
        <p className="mt-3 text-lg font-semibold text-slate-900 whitespace-pre-line">{done}</p>
        <p className="mt-1 text-sm text-slate-500">Vous pouvez fermer cette page.</p>
      </div>,
    );
  }
  if (s.closed) {
    return shell(
      <div className="rounded-2xl bg-white p-8 shadow text-center" data-testid="survey-closed">
        <Lock className="h-10 w-10 mx-auto text-slate-400" />
        <p className="mt-3 font-semibold text-slate-900">{s.title}</p>
        <p className="mt-1 text-sm text-slate-500">Ce sondage est clôturé. Merci de votre intérêt.</p>
      </div>,
    );
  }

  const btn = (active) => `rounded-xl px-4 py-3 text-sm font-medium ring-1 transition text-left ${active ? "bg-emerald-600 text-white ring-emerald-600" : "bg-white ring-slate-200 hover:ring-emerald-400"}`;
  return shell(
    <div className="space-y-4" data-testid="public-survey">
      <div className="rounded-2xl bg-white p-5 shadow">
        {s.respondent && <p className="text-sm text-emerald-700 font-medium">Bonjour {s.respondent} 👋</p>}
        <h1 className="text-xl font-bold text-slate-900">{s.title}</h1>
        {s.description && <p className="mt-2 text-sm text-slate-600 whitespace-pre-line">{s.description}</p>}
        {s.already_answered && <p className="mt-2 text-xs rounded-lg bg-sky-50 text-sky-700 px-2 py-1">Vous avez déjà répondu : vous pouvez corriger vos réponses.</p>}
      </div>
      {s.questions.map((q, i) => (
        <div key={q.id} id={`q-${q.id}`} className={`rounded-2xl bg-white p-5 shadow ${missing === q.id ? "ring-2 ring-rose-400" : ""}`} data-testid={`pq-${i}`}>
          <p className="font-semibold text-slate-900">{i + 1}. {q.label}{q.required && <span className="text-rose-500"> *</span>}</p>
          {q.help && <p className="text-xs text-slate-500 mt-0.5">{q.help}</p>}
          <div className="mt-3">
            {q.type === "single" && (
              <div className="grid gap-2">{q.options.map((o) => <button key={o} onClick={() => set(q.id, o)} className={btn(answers[q.id] === o)}>{o}</button>)}</div>
            )}
            {q.type === "multi" && (
              <div className="grid gap-2">
                {q.options.map((o) => {
                  const on = (answers[q.id] || []).includes(o);
                  return <button key={o} onClick={() => toggleMulti(q.id, o)} className={btn(on)}>{on ? "☑" : "☐"} {o}</button>;
                })}
                <p className="text-[11px] text-slate-400">Plusieurs choix possibles</p>
              </div>
            )}
            {q.type === "yesno" && (
              <div className="grid grid-cols-2 gap-2">
                {[["oui", "Oui"], ["non", "Non"]].map(([v, l]) => <button key={v} onClick={() => set(q.id, v)} className={`${btn(answers[q.id] === v)} text-center`}>{l}</button>)}
              </div>
            )}
            {q.type === "rating" && (
              <div className="flex gap-1" role="radiogroup">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button key={n} onClick={() => set(q.id, n)} aria-label={`${n} sur 5`} data-testid={`pq-${i}-star-${n}`}>
                    <Star className={`h-10 w-10 transition ${(answers[q.id] || 0) >= n ? "text-amber-400 fill-amber-400" : "text-slate-300"}`} />
                  </button>
                ))}
              </div>
            )}
            {q.type === "nps" && (
              <div>
                <div className="grid grid-cols-11 gap-1">
                  {Array.from({ length: 11 }, (_, n) => (
                    <button key={n} onClick={() => set(q.id, n)} data-testid={`pq-${i}-nps-${n}`}
                      className={`rounded-lg py-2 text-sm font-semibold ring-1 ${answers[q.id] === n ? (n >= 9 ? "bg-emerald-600" : n >= 7 ? "bg-amber-500" : "bg-rose-500") + " text-white ring-transparent" : "bg-white ring-slate-200"}`}>
                      {n}
                    </button>
                  ))}
                </div>
                <div className="mt-1 flex justify-between text-[10px] text-slate-400"><span>Pas du tout probable</span><span>Très probable</span></div>
              </div>
            )}
            {q.type === "text" && (
              <textarea value={answers[q.id] || ""} onChange={(e) => set(q.id, e.target.value)} rows={3} maxLength={2000}
                className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" placeholder="Votre réponse" data-testid={`pq-${i}-text`} />
            )}
          </div>
          {missing === q.id && <p className="mt-2 text-xs text-rose-600">Cette question est obligatoire.</p>}
        </div>
      ))}
      {error && <p className="rounded-lg bg-rose-50 text-rose-700 text-sm px-3 py-2">{error}</p>}
      <button onClick={submit} disabled={sending} data-testid="survey-submit"
        className="w-full inline-flex items-center justify-center gap-2 rounded-2xl bg-emerald-600 text-white py-4 text-base font-semibold shadow hover:bg-emerald-700 disabled:opacity-50">
        {sending ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />} {s.already_answered ? "Mettre à jour mes réponses" : "Envoyer mes réponses"}
      </button>
      <p className="text-center text-[11px] text-slate-400">Vos réponses sont transmises uniquement à l'organisateur du sondage.</p>
    </div>,
  );
}
