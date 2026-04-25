import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { LOGO_URL } from "@/lib/brand";
import { CheckCircle2, AlertCircle, Star } from "lucide-react";
import { toast } from "sonner";

export default function Feedback() {
  const { token } = useParams();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [score, setScore] = useState(null);
  const [hover, setHover] = useState(null);
  const [comment, setComment] = useState("");
  const [allowPublish, setAllowPublish] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    apiClient.get(`/feedback/${token}`).then((r) => setInfo(r.data))
      .catch((e) => setError(e?.response?.data?.detail || "Lien invalide"));
  }, [token]);

  const submit = async (e) => {
    e.preventDefault();
    if (score === null) return toast.error("Sélectionnez une note");
    setSubmitting(true);
    try {
      await apiClient.post(`/feedback/${token}`, { score, comment, allow_publish: allowPublish });
      setSuccess(true);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSubmitting(false); }
  };

  if (error) {
    return (
      <Wrapper>
        <div className="text-center" data-testid="feedback-error">
          <AlertCircle className="h-10 w-10 text-amber-300 mx-auto" />
          <h1 className="mt-4 text-2xl font-display font-bold">Lien invalide</h1>
          <p className="mt-2 text-slate-300">{error}</p>
          <Link to="/" className="mt-6 inline-block text-sawali-blue-light underline">Retour au site</Link>
        </div>
      </Wrapper>
    );
  }
  if (!info) return <Wrapper><p className="text-slate-400 text-center">Chargement...</p></Wrapper>;
  if (success) {
    return (
      <Wrapper>
        <div className="text-center" data-testid="feedback-success">
          <CheckCircle2 className="h-12 w-12 text-emerald-300 mx-auto" />
          <h1 className="mt-4 text-3xl font-display font-bold">Merci pour votre retour !</h1>
          <p className="mt-3 text-slate-300">Votre témoignage nous aide à progresser. Il sera modéré avant publication.</p>
          <Link to="/" className="mt-8 inline-block btn-electric rounded-lg px-5 py-2.5 text-sm font-medium">Retour au site</Link>
        </div>
      </Wrapper>
    );
  }

  const npsLabel = score === null ? "" : score >= 9 ? "Promoteur" : score >= 7 ? "Passif" : "Détracteur";

  return (
    <Wrapper>
      <form onSubmit={submit} className="space-y-6" data-testid="feedback-form">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">Évaluation NPS</p>
          <h1 className="mt-2 text-3xl font-display font-bold">Votre avis compte, {info.client_name.split(" ")[0]}.</h1>
          <p className="mt-3 text-slate-300">
            Vous avez récemment échangé avec nous au sujet de <strong className="text-white">"{info.subject}"</strong>. Quelle est la probabilité que vous recommandiez SAWALI à un confrère ?
          </p>
        </div>

        <div>
          <div className="flex flex-wrap gap-1.5 sm:gap-2" onMouseLeave={() => setHover(null)} data-testid="score-buttons">
            {Array.from({ length: 11 }).map((_, n) => {
              const active = (hover ?? score) >= n;
              return (
                <button
                  type="button" key={n}
                  onMouseEnter={() => setHover(n)}
                  onClick={() => setScore(n)}
                  className={`h-11 w-11 sm:h-12 sm:w-12 rounded-lg border text-sm font-display font-semibold transition ${
                    active ? "bg-sawali-blue text-white border-sawali-blue" : "border-white/20 text-slate-300 hover:border-sawali-blue/50"
                  }`}
                  data-testid={`score-${n}`}
                >
                  {n}
                </button>
              );
            })}
          </div>
          <div className="mt-2 flex justify-between text-[10px] uppercase tracking-widest text-slate-500">
            <span>Pas du tout</span>
            <span>Très probablement</span>
          </div>
          {score !== null && (
            <p className="mt-3 text-sm text-sawali-blue-light">Vous êtes catégorisé : <strong>{npsLabel}</strong></p>
          )}
        </div>

        <div>
          <label className="block text-xs uppercase tracking-[0.2em] text-slate-400 mb-2">Votre commentaire (optionnel)</label>
          <textarea
            rows={5} value={comment} onChange={(e) => setComment(e.target.value)}
            className="w-full rounded-lg bg-white/5 border border-white/10 text-white px-4 py-3 text-sm focus:outline-none focus:border-sawali-blue"
            placeholder="Qu'avez-vous le plus apprécié ? Que pourrions-nous améliorer ?"
            data-testid="feedback-comment"
          />
        </div>

        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={allowPublish} onChange={(e) => setAllowPublish(e.target.checked)} data-testid="feedback-allow-publish" />
          J'accepte que mon témoignage soit publié sur le site (avec mon nom et mon entreprise)
        </label>

        <button
          type="submit" disabled={submitting || score === null}
          className="btn-electric inline-flex items-center justify-center gap-2 rounded-lg px-6 py-3 font-medium disabled:opacity-50 w-full sm:w-auto"
          data-testid="feedback-submit"
        >
          <Star className="h-4 w-4" /> {submitting ? "Envoi..." : "Envoyer mon témoignage"}
        </button>
      </form>
    </Wrapper>
  );
}

const Wrapper = ({ children }) => (
  <div className="min-h-screen marketing-dark py-10 px-4">
    <div className="mx-auto max-w-2xl">
      <Link to="/" className="flex items-center gap-3 mb-8">
        <img src={LOGO_URL} alt="SAWALI" className="h-10 w-10 rounded-md ring-1 ring-white/20" />
        <div>
          <p className="font-display font-bold">SAWALI SMART SYSTEMS</p>
          <p className="text-[10px] uppercase tracking-[0.3em] text-sawali-blue-light">Software Engineering</p>
        </div>
      </Link>
      <div className="glow-card rounded-2xl p-6 sm:p-10">{children}</div>
    </div>
  </div>
);
