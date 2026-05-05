import React, { useEffect, useState } from "react";
import { useParams, Link, Navigate } from "react-router-dom";
import { Shield, FileText, Trash2, Download, ExternalLink, ChevronRight } from "lucide-react";

const SLOTS = [
  {
    slug: "confidentialite",
    apiSlot: "privacy",
    label: "Politique de confidentialité (RGPD)",
    description:
      "Comment SAWALI SMART SYSTEMS collecte, traite et protège vos données personnelles. Conformité RGPD et exercice de vos droits (accès, rectification, suppression).",
    icon: Shield,
  },
  {
    slug: "services",
    apiSlot: "services",
    label: "Politique de services",
    description:
      "Modalités de fourniture de nos services, niveaux de service, support technique, et engagements de qualité.",
    icon: FileText,
  },
  {
    slug: "suppression",
    apiSlot: "deletion",
    label: "Politique de suppression",
    description:
      "Procédure pour demander la suppression de vos données conformément au RGPD et durée de conservation.",
    icon: Trash2,
  },
];

export default function PoliciesPage() {
  const { slug } = useParams();
  const item = SLOTS.find((s) => s.slug === slug);

  if (!slug) return <PoliciesIndex />;
  if (!item) return <Navigate to="/politiques" replace />;
  return <PolicyDetail item={item} />;
}

function PoliciesIndex() {
  return (
    <section className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 py-12 lg:py-16" data-testid="policies-index">
      <header className="mb-8">
        <p className="text-xs uppercase tracking-[0.3em] text-sawali-blue-light mb-2">Mentions légales</p>
        <h1 className="text-3xl sm:text-4xl font-display font-bold text-white">Politiques publiques</h1>
        <p className="mt-3 text-slate-300 max-w-2xl">
          Documents officiels de SAWALI SMART SYSTEMS. Ces politiques s'appliquent à tous les services hébergés sur nos
          domaines (sawalismartsystems.com, etc.).
        </p>
      </header>
      <div className="grid sm:grid-cols-2 gap-4">
        {SLOTS.map((s) => (
          <Link
            key={s.slug}
            to={`/politiques/${s.slug}`}
            className="group rounded-2xl ring-1 ring-white/10 bg-white/5 hover:bg-white/10 transition p-5 backdrop-blur"
            data-testid={`policy-card-${s.slug}`}
          >
            <div className="flex items-start gap-3">
              <div className="rounded-lg bg-sawali-blue/20 p-2.5">
                <s.icon className="h-5 w-5 text-sawali-blue-light" />
              </div>
              <div className="flex-1">
                <h3 className="font-display font-semibold text-white group-hover:text-sawali-blue-light">{s.label}</h3>
                <p className="text-xs text-slate-400 mt-1">{s.description}</p>
              </div>
              <ChevronRight className="h-4 w-4 text-slate-500 group-hover:text-sawali-blue-light mt-1" />
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

function PolicyDetail({ item }) {
  const [error, setError] = useState(false);
  const Icn = item.icon;
  const pdfUrl = `/api/public/policies/${item.apiSlot}`;

  useEffect(() => {
    // Quick HEAD check — if 404 we still show the description, but mark it as not yet uploaded
    fetch(pdfUrl, { method: "HEAD" })
      .then((r) => { if (!r.ok) setError(true); })
      .catch(() => setError(true));
  }, [pdfUrl]);

  return (
    <section className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8 py-10 space-y-6" data-testid={`policy-detail-${item.slug}`}>
      <nav className="text-xs text-slate-400">
        <Link to="/" className="hover:text-white">Accueil</Link>
        <span className="mx-1.5">›</span>
        <Link to="/politiques" className="hover:text-white">Politiques</Link>
        <span className="mx-1.5">›</span>
        <span className="text-slate-300">{item.label}</span>
      </nav>

      <header className="rounded-2xl bg-white/5 ring-1 ring-white/10 p-6 backdrop-blur">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-sawali-blue/20 p-3 shrink-0">
            <Icn className="h-6 w-6 text-sawali-blue-light" />
          </div>
          <div className="flex-1">
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-white">{item.label}</h1>
            <p className="text-sm text-slate-300 mt-2">{item.description}</p>
            <div className="mt-4 flex gap-2 flex-wrap">
              <a
                href={pdfUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-3 py-1.5 text-xs font-semibold hover:bg-sawali-blue-light"
                data-testid={`policy-open-${item.slug}`}
              >
                <ExternalLink className="h-3.5 w-3.5" /> Ouvrir le PDF
              </a>
              <a
                href={pdfUrl}
                download
                className="inline-flex items-center gap-2 rounded-lg ring-1 ring-white/20 text-white px-3 py-1.5 text-xs font-semibold hover:bg-white/10"
                data-testid={`policy-download-${item.slug}`}
              >
                <Download className="h-3.5 w-3.5" /> Télécharger
              </a>
            </div>
          </div>
        </div>
      </header>

      {error ? (
        <div className="rounded-2xl bg-amber-50 ring-1 ring-amber-200 p-6 text-sm text-amber-900">
          Cette politique n'est pas encore publiée. Merci de votre patience — nous mettons à disposition cette information
          au plus vite. En attendant, vous pouvez nous contacter à <strong>contact@sawalismartsystems.com</strong>.
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden ring-1 ring-white/10 bg-white">
          <iframe
            src={pdfUrl}
            title={item.label}
            className="w-full h-[80vh]"
            data-testid={`policy-iframe-${item.slug}`}
          />
        </div>
      )}
    </section>
  );
}
