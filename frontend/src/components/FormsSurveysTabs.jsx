/*
  FormsSurveysTabs — lot 27 : bascule entre les deux portefeuilles
  « Formulaires » et « Sondages WhatsApp », en tête de leurs pages.
  Le préfixe (/portal ou /admin) suit la page courante.
  Lot 41 : chaque onglet porte la bulle des nouvelles données (verte : formulaires,
  bleue : sondages), comme la barre latérale.
*/
import React, { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { FileText, BarChart3 } from "lucide-react";
import { lireNouveautes } from "@/lib/nouveautesFormulaires";

export default function FormsSurveysTabs({ active }) {
  const { pathname } = useLocation();
  const base = pathname.startsWith("/admin") ? "/admin" : "/portal";
  const [nouveaux, setNouveaux] = useState({ formulaires: 0, sondages: 0 });
  useEffect(() => { lireNouveautes().then(setNouveaux); }, [pathname]);
  const tabs = [
    ["forms", "Formulaires", FileText, `${base}/forms`, nouveaux.formulaires, "bg-emerald-500"],
    ["surveys", "Sondages WhatsApp", BarChart3, `${base}/surveys`, nouveaux.sondages, "bg-sky-500"],
  ];
  return (
    <div className="inline-flex rounded-xl bg-slate-100 p-1" data-testid="forms-surveys-tabs">
      {tabs.map(([key, label, Icon, to, n, couleur]) => (
        <Link key={key} to={to} data-testid={`tab-${key}`}
          className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition ${active === key ? "bg-white text-sawali-blue shadow-sm" : "text-slate-500 hover:text-slate-900"}`}>
          <Icon className="h-4 w-4" /> {label}
          {n > 0 && (
            <span className={`inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-white text-[10px] font-bold ${couleur}`}
              title="Nouvelles données reçues" data-testid={`tab-${key}-new`}>
              {n > 99 ? "99+" : n}
            </span>
          )}
        </Link>
      ))}
    </div>
  );
}
