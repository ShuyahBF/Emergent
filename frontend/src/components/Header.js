import { useEffect, useState } from "react";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { LogOut, Settings, ArrowLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function Header({ user, onLogout, showBack = false, showSettings = false, title, subtitle }) {
  const navigate = useNavigate();
  const [settings, setSettings] = useState(null);

  useEffect(() => {
    // Récupérer les paramètres pour le logo (sans auth requise)
    const fetchSettings = async () => {
      try {
        const response = await axios.get(`${API}/settings/public`);
        setSettings(response.data);
      } catch (error) {
        // Silencieux - le logo n'est pas critique
      }
    };
    fetchSettings();
  }, []);

  return (
    <header className="sticky top-0 z-50 backdrop-blur-md bg-white/80 border-b border-slate-200 h-16">
      <div className="max-w-7xl mx-auto px-6 h-full flex items-center justify-between">
        <div className="flex items-center gap-4">
          {showBack && (
            <>
              <Button
                data-testid="back-button"
                onClick={() => navigate("/")}
                variant="ghost"
                className="rounded-sm hover:bg-slate-100"
              >
                <ArrowLeft className="h-4 w-4 mr-2" />
                Retour
              </Button>
              <div className="border-l border-slate-300 h-6 mx-2"></div>
            </>
          )}
          <div className="flex items-center gap-3">
            {settings?.company_logo && (
              <img
                src={settings.company_logo}
                alt={settings.company_name || "Logo"}
                className="h-10 w-auto object-contain"
                onError={(e) => e.target.style.display = 'none'}
              />
            )}
            <div>
              <h1 className="text-xl font-bold text-slate-900">
                {title || settings?.site_title || "Justification Comptable"}
              </h1>
              {subtitle && <p className="text-xs text-slate-600">{subtitle}</p>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {showSettings && user?.role === "superviseur" && (
            <Button
              data-testid="settings-button"
              onClick={() => navigate("/settings")}
              variant="ghost"
              className="rounded-sm hover:bg-slate-100"
            >
              <Settings className="h-4 w-4 mr-2" />
              Paramètres
            </Button>
          )}
          {onLogout && (
            <Button
              data-testid="logout-button"
              onClick={onLogout}
              variant="ghost"
              className="rounded-sm hover:bg-slate-100"
            >
              <LogOut className="h-4 w-4 mr-2" />
              Déconnexion
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}