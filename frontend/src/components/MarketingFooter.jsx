import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Mail, Phone, MapPin } from "lucide-react";
import { LOGO_URL } from "@/lib/brand";
import { apiClient } from "@/lib/api";

export default function MarketingFooter() {
  const [info, setInfo] = useState(null);
  useEffect(() => {
    apiClient.get("/company-info").then((r) => setInfo(r.data)).catch(() => {});
  }, []);
  return (
    <footer className="bg-[#050b18] text-slate-300 border-t border-white/10" data-testid="marketing-footer">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-14 grid gap-10 md:grid-cols-4">
        <div>
          <div className="flex items-center gap-3 mb-3">
            <img src={LOGO_URL} alt="SAWALI" className="h-10 w-10 rounded-md object-cover" />
            <div>
              <p className="font-display font-bold text-white">SAWALI SMART SYSTEMS</p>
              <p className="text-[10px] uppercase tracking-[0.25em] text-sawali-blue-light">Software Engineering</p>
            </div>
          </div>
          <p className="text-sm leading-relaxed">
            Société d'ingénierie logicielle. Conception, déploiement et maintenance
            de solutions métiers sur-mesure.
          </p>
        </div>
        <div>
          <p className="font-display font-semibold text-white mb-3">Navigation</p>
          <ul className="space-y-2 text-sm">
            <li><Link to="/missions" className="hover:text-sawali-blue-light">Missions</Link></li>
            <li><Link to="/specialisations" className="hover:text-sawali-blue-light">Spécialisations</Link></li>
            <li><Link to="/catalogue" className="hover:text-sawali-blue-light">Catalogue</Link></li>
            <li><Link to="/rdv" className="hover:text-sawali-blue-light">Demande de RDV</Link></li>
          </ul>
        </div>
        <div>
          <p className="font-display font-semibold text-white mb-3">Espaces</p>
          <ul className="space-y-2 text-sm">
            <li><Link to="/login" className="hover:text-sawali-blue-light">Connexion client</Link></li>
            <li><Link to="/contact" className="hover:text-sawali-blue-light">Contact</Link></li>
            <li><Link to="/documentation" className="hover:text-sawali-blue-light">Documentation API</Link></li>
          </ul>
        </div>
        <div>
          <p className="font-display font-semibold text-white mb-3">Contact</p>
          <ul className="space-y-2 text-sm">
            <li className="flex items-center gap-2"><Mail className="h-4 w-4 text-sawali-blue-light" /> {info?.email || "..."}</li>
            <li className="flex items-center gap-2"><Phone className="h-4 w-4 text-sawali-blue-light" /> {info?.phone || "..."}</li>
            <li className="flex items-center gap-2"><MapPin className="h-4 w-4 text-sawali-blue-light" /> {info?.address || "..."}</li>
          </ul>
        </div>
      </div>
      <div className="border-t border-white/5 py-5 text-center text-xs text-slate-500">
        © {new Date().getFullYear()} SAWALI SMART SYSTEMS. Tous droits réservés.
      </div>
    </footer>
  );
}
