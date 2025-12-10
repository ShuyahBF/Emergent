import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function Login({ onLogin }) {
  const [isRegister, setIsRegister] = useState(false);
  const [formData, setFormData] = useState({
    email: "",
    password: "",
    nom: ""
  });
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      const endpoint = isRegister ? `${API}/auth/register` : `${API}/auth/login`;
      const payload = isRegister
        ? { email: formData.email, password: formData.password, nom: formData.nom }
        : { email: formData.email, password: formData.password };

      const response = await axios.post(endpoint, payload);
      const { access_token, user } = response.data;

      toast.success(isRegister ? "Compte créé avec succès" : "Connexion réussie");
      onLogin(access_token, user);
    } catch (error) {
      const message = error.response?.data?.detail || "Une erreur est survenue";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      {/* Left Side - Image */}
      <div
        className="hidden lg:flex lg:w-1/2 bg-cover bg-center relative"
        style={{
          backgroundImage: `url('https://images.unsplash.com/photo-1491183846256-33aec7637311?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDk1Nzl8MHwxfHNlYXJjaHwyfHxtaW5pbWFsaXN0JTIwYWJzdHJhY3QlMjBnZW9tZXRyaWMlMjB3aGl0ZSUyMGJhY2tncm91bmR8ZW58MHx8fHwxNzY1Mzk2MDkyfDA&ixlib=rb-4.1.0&q=85')`
        }}
      >
        <div className="absolute inset-0 bg-gradient-to-br from-slate-900/40 to-slate-900/20"></div>
        <div className="relative z-10 flex flex-col justify-end p-12 text-white">
          <h1 className="text-4xl font-bold mb-4">Justification de Pièces Comptables</h1>
          <p className="text-lg text-slate-200">Solution professionnelle pour la vérification et la justification de vos écritures comptables</p>
        </div>
      </div>

      {/* Right Side - Form */}
      <div className="flex-1 flex items-center justify-center p-8 bg-slate-50">
        <Card className="w-full max-w-md shadow-lg border-slate-200">
          <CardHeader className="space-y-1">
            <CardTitle className="text-2xl font-bold">
              {isRegister ? "Créer un compte" : "Connexion"}
            </CardTitle>
            <CardDescription>
              {isRegister
                ? "Remplissez les informations pour créer votre compte"
                : "Entrez vos identifiants pour accéder à votre espace"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              {isRegister && (
                <div className="space-y-2">
                  <Label htmlFor="nom" data-testid="nom-label">Nom complet</Label>
                  <Input
                    id="nom"
                    data-testid="nom-input"
                    type="text"
                    placeholder="Jean Dupont"
                    value={formData.nom}
                    onChange={(e) => setFormData({ ...formData, nom: e.target.value })}
                    required={isRegister}
                    className="rounded-sm"
                  />
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="email" data-testid="email-label">Email</Label>
                <Input
                  id="email"
                  data-testid="email-input"
                  type="email"
                  placeholder="jean.dupont@exemple.fr"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  required
                  className="rounded-sm"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="password" data-testid="password-label">Mot de passe</Label>
                <Input
                  id="password"
                  data-testid="password-input"
                  type="password"
                  placeholder="••••••••"
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  required
                  className="rounded-sm"
                />
              </div>

              <Button
                type="submit"
                data-testid="submit-button"
                className="w-full rounded-sm bg-slate-900 hover:bg-slate-800 active:scale-95 transition-all"
                disabled={loading}
              >
                {loading ? "Chargement..." : isRegister ? "Créer le compte" : "Se connecter"}
              </Button>
            </form>

            <div className="mt-6 text-center">
              <button
                type="button"
                data-testid="toggle-mode-button"
                onClick={() => setIsRegister(!isRegister)}
                className="text-sm text-slate-600 hover:text-slate-900 transition-colors"
              >
                {isRegister
                  ? "Vous avez déjà un compte ? Connectez-vous"
                  : "Pas encore de compte ? Inscrivez-vous"}
              </button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}