// AlertesPlateformesBanner.jsx — Lot 352 : bandeau rouge des pannes des plateformes externes (Meta/WhatsApp : paiement, jeton,
// compte restreint…). Visible UNIQUEMENT pour l'administrateur (super-admin), sur les pages /admin, comme le bandeau du crédit IA.
// Relit /api/admin/alertes-plateformes toutes les 60 s. Le détail (« Que faire ») s'affiche dans le bandeau ; « Historique par WABA »
// ouvre la rubrique des Paramètres.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { AlertTriangle } from "lucide-react";
import { siVisible } from "@/lib/visibilite";

const SUPER_ADMIN_EMAIL = "admin@sawalismartsystems.com";
const POLL_MS = 60_000;

export default function AlertesPlateformesBanner() {
  const { user } = useAuth() || {};
  const location = useLocation();
  const [alertes, setAlertes] = useState([]);
  const minuteur = useRef(null);
  // Réservé à l'administrateur, pages /admin uniquement
  const visible = !!user && (user?.email || "").toLowerCase() === SUPER_ADMIN_EMAIL && (location?.pathname || "").startsWith("/admin");

  const lire = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/alertes-plateformes");
      setAlertes(r.data?.ouvertes || []);
    } catch { /* silencieux : un autre compte reçoit 403, c'est normal */ }
  }, []);

  useEffect(() => {
    if (!visible) return undefined;
    lire();
    minuteur.current = setInterval(siVisible(lire), POLL_MS);
    return () => clearInterval(minuteur.current);
  }, [visible, lire]);

  if (!visible || alertes.length === 0) return null;
  return (
    <div className="sticky top-0 z-[80] bg-gradient-to-r from-rose-600 to-red-700 text-white shadow-lg" role="alert" data-testid="alertes-plateformes-banner">
      <div className="max-w-7xl mx-auto px-4 py-2 space-y-2">
        {alertes.map((a) => (
          <div key={a.cle} className="flex items-start gap-3 text-sm">
            <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5 animate-pulse" />
            <div className="min-w-0 flex-1">
              <p className="font-bold leading-tight">{a.titre} <span className="font-normal text-xs opacity-90">· WABA {a.waba_id || "—"} · {a.nombre} message(s) en échec · depuis {new Date(a.depuis).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</span></p>
              <p className="text-xs opacity-95 leading-tight mt-0.5"><strong>Que faire :</strong> {a.action}</p>
            </div>
          </div>
        ))}
        <p className="text-xs"><Link to="/admin/settings#s-alertes-plateformes" className="underline font-semibold">Historique par WABA et PDF</Link></p>
      </div>
    </div>
  );
}
