import React from "react";
import { useLocation } from "react-router-dom";
import { Hammer, Mail } from "lucide-react";

/*
  Generic placeholder for modules that are scheduled but not yet developed.
  Used by /portal/cash, /portal/billing, /portal/catalog, /portal/tickets.
*/
const MODULE_INFO = {
  "/portal/cash": {
    title: "Caisse",
    pitch: "Encaissements en magasin et tickets de caisse — bientôt disponible.",
    bullets: [
      "Saisie rapide des transactions du jour",
      "Sélection de produit depuis le catalogue",
      "Lien automatique vers un envoi par WhatsApp / SMS du ticket",
    ],
  },
  "/portal/billing": {
    title: "Facturation",
    pitch: "Génération de devis et factures avec envoi WhatsApp / SMS au client.",
    bullets: [
      "Modèles de facture personnalisables",
      "Envoi par WhatsApp ou SMS avec lien de paiement PawaPay intégré",
      "Suivi des relances et statuts de paiement",
    ],
  },
  "/portal/catalog": {
    title: "Catalogue",
    pitch: "Catalogue produits/services réutilisable dans la Caisse et la Facturation.",
    bullets: [
      "Catégories, prix HT/TTC, photos",
      "Stock simple (nombre d'unités disponibles)",
      "Import/export Excel/CSV",
    ],
  },
  "/portal/tickets": {
    title: "Tickets",
    pitch: "Gestion centralisée des tickets de support — bientôt disponible.",
    bullets: [
      "Création depuis WhatsApp/SMS/Email",
      "Statuts (ouvert, en cours, résolu) et SLA",
      "Affectation à un membre de l'équipe + historique",
    ],
  },
};

export default function ComingSoon() {
  const loc = useLocation();
  const info = MODULE_INFO[loc.pathname] || {
    title: "Module",
    pitch: "Cette fonctionnalité arrive prochainement.",
    bullets: [],
  };

  return (
    <div className="max-w-2xl space-y-6" data-testid="coming-soon-page">
      <div className="rounded-2xl bg-gradient-to-br from-sawali-blue/10 via-white to-fuchsia-50 ring-1 ring-slate-200 p-8">
        <div className="inline-flex items-center justify-center h-14 w-14 rounded-2xl bg-amber-100 ring-1 ring-amber-200 mb-4">
          <Hammer className="h-7 w-7 text-amber-600" />
        </div>
        <p className="text-[10px] uppercase tracking-[0.3em] text-slate-500">En développement</p>
        <h1 className="text-3xl font-display font-bold mt-1" data-testid="coming-soon-title">
          {info.title}
        </h1>
        <p className="text-slate-600 mt-3 text-sm leading-relaxed">{info.pitch}</p>
        {info.bullets.length > 0 && (
          <ul className="mt-5 space-y-2">
            {info.bullets.map((b, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-slate-700">
                <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-sawali-blue flex-shrink-0" />
                <span>{b}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-6 flex items-center gap-2 text-[12px] text-slate-500 bg-white/60 rounded-lg ring-1 ring-slate-200 px-3 py-2">
          <Mail className="h-3.5 w-3.5" />
          Une question ou une priorité particulière ? Écrivez-nous depuis le formulaire de contact ou via WhatsApp.
        </div>
      </div>
    </div>
  );
}
