/*
  FormsSurveysTabs — lot 27 : bascule entre les deux portefeuilles
  « Formulaires » et « Sondages WhatsApp », en tête de leurs pages.
  Le préfixe (/portal ou /admin) suit la page courante.
*/
import React from "react";
import { Link, useLocation } from "react-router-dom";
import { FileText, BarChart3 } from "lucide-react";

export default function FormsSurveysTabs({ active }) {
  const { pathname } = useLocation();
  const base = pathname.startsWith("/admin") ? "/admin" : "/portal";
  const tabs = [
    ["forms", "Formulaires", FileText, `${base}/forms`],
    ["surveys", "Sondages WhatsApp", BarChart3, `${base}/surveys`],
  ];
  return (
    <div className="inline-flex rounded-xl bg-slate-100 p-1" data-testid="forms-surveys-tabs">
      {tabs.map(([key, label, Icon, to]) => (
        <Link key={key} to={to} data-testid={`tab-${key}`}
          className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition ${active === key ? "bg-white text-sawali-blue shadow-sm" : "text-slate-500 hover:text-slate-900"}`}>
          <Icon className="h-4 w-4" /> {label}
        </Link>
      ))}
    </div>
  );
}
