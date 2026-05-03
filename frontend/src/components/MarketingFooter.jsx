import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Mail, Phone, MapPin, MessageCircle } from "lucide-react";
import { LOGO_URL } from "@/lib/brand";
import { apiClient } from "@/lib/api";
import NewsletterForm from "@/components/NewsletterForm";

export default function MarketingFooter() {
  const [info, setInfo] = useState(null);
  useEffect(() => {
    apiClient.get("/company-info").then((r) => setInfo(r.data)).catch(() => {});
  }, []);
  return (
    <footer className="bg-[#050b18] text-slate-300 border-t border-white/10" data-testid="marketing-footer">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10 border-b border-white/5">
        <div className="grid lg:grid-cols-2 gap-6 items-center">
          <div>
            <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">Newsletter</p>
            <h3 className="mt-2 font-display font-bold text-white text-xl">Restez à la pointe de l'ingénierie logicielle.</h3>
          </div>
          <NewsletterForm />
        </div>
      </div>
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
            <li><Link to="/etudes-de-cas" className="hover:text-sawali-blue-light">Études de cas</Link></li>
            <li><Link to="/blog" className="hover:text-sawali-blue-light">Blog</Link></li>
            <li><Link to="/temoignages" className="hover:text-sawali-blue-light">Témoignages</Link></li>
            <li><Link to="/rdv" className="hover:text-sawali-blue-light">Demande de RDV</Link></li>
          </ul>
        </div>
        <div>
          <p className="font-display font-semibold text-white mb-3">Espaces</p>
          <ul className="space-y-2 text-sm">
            <li><Link to="/login" className="hover:text-sawali-blue-light">Connexion client</Link></li>
            <li><Link to="/contact" className="hover:text-sawali-blue-light">Contact</Link></li>
            <li><Link to="/documentation" className="hover:text-sawali-blue-light">Documentation API</Link></li>
            <li><Link to="/uptime" className="hover:text-sawali-blue-light">État des services</Link></li>
          </ul>
        </div>
        <div>
          <p className="font-display font-semibold text-white mb-3">Contact</p>
          <ul className="space-y-2 text-sm">
            <li className="flex items-center gap-2"><Mail className="h-4 w-4 text-sawali-blue-light" /> {info?.email || "..."}</li>
            <li className="flex items-center gap-2"><Phone className="h-4 w-4 text-sawali-blue-light" /> {info?.phone || "..."}</li>
            {info?.whatsapp && (
              <li className="flex items-center gap-2"><MessageCircle className="h-4 w-4 text-emerald-400" /> WhatsApp : {info.whatsapp}</li>
            )}
            <li className="flex items-center gap-2"><MapPin className="h-4 w-4 text-sawali-blue-light" /> {[info?.address, info?.city, info?.country].filter(Boolean).join(", ") || "..."}</li>
          </ul>
        </div>
      </div>
      <div className="border-t border-white/5 py-5 text-center text-xs text-slate-500">
        <div className="flex items-center justify-center gap-3 mb-2 flex-wrap" data-testid="footer-policy-links">
          <a href="/api/public/policies/privacy" target="_blank" rel="noopener noreferrer" className="hover:text-white transition" data-testid="footer-policy-privacy">Politique de confidentialité</a>
          <span className="text-slate-700">·</span>
          <a href="/api/public/policies/services" target="_blank" rel="noopener noreferrer" className="hover:text-white transition" data-testid="footer-policy-services">Politique de services</a>
          <span className="text-slate-700">·</span>
          <a href="/api/public/policies/deletion" target="_blank" rel="noopener noreferrer" className="hover:text-white transition" data-testid="footer-policy-deletion">Politique de suppression</a>
        </div>
        © {new Date().getFullYear()} SAWALI SMART SYSTEMS. Tous droits réservés.
      </div>
    </footer>
  );
}
