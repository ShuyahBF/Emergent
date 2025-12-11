import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ArrowLeft, LogOut, Save, Users, Settings as SettingsIcon, Webhook } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function Settings({ user, onLogout }) {
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (user.role !== "superviseur") {
      toast.error("Accès refusé");
      navigate("/");
      return;
    }
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const token = localStorage.getItem("token");
      const [usersRes, settingsRes] = await Promise.all([
        axios.get(`${API}/users`, {
          headers: { Authorization: `Bearer ${token}` }
        }),
        axios.get(`${API}/settings`, {
          headers: { Authorization: `Bearer ${token}` }
        })
      ]);
      setUsers(usersRes.data);
      setSettings(settingsRes.data);
    } catch (error) {
      toast.error("Erreur lors du chargement des données");
    } finally {
      setLoading(false);
    }
  };

  const handleRoleChange = async (userId, newRole) => {
    try {
      const token = localStorage.getItem("token");
      await axios.put(`${API}/users/${userId}/role`, 
        { role: newRole },
        { headers: { Authorization: `Bearer ${token}` }}
      );
      toast.success("Rôle mis à jour");
      fetchData();
    } catch (error) {
      toast.error("Erreur lors de la mise à jour du rôle");
    }
  };

  const handleSaveSettings = async () => {
    setSaving(true);
    try {
      const token = localStorage.getItem("token");
      await axios.put(`${API}/settings`, settings, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success("Paramètres sauvegardés");
    } catch (error) {
      toast.error("Erreur lors de la sauvegarde");
    } finally {
      setSaving(false);
    }
  };

  const getRoleBadgeColor = (role) => {
    switch (role) {
      case "superviseur":
        return "bg-purple-100 text-purple-700";
      case "modification":
        return "bg-blue-100 text-blue-700";
      default:
        return "bg-gray-100 text-gray-700";
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-slate-900"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="sticky top-0 z-50 backdrop-blur-md bg-white/80 border-b border-slate-200 h-16">
        <div className="max-w-7xl mx-auto px-6 h-full flex items-center justify-between">
          <div className="flex items-center gap-4">
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
            <div>
              <h1 className="text-lg font-bold text-slate-900">Paramètres & Configuration</h1>
              <p className="text-xs text-slate-600">Gestion du site</p>
            </div>
          </div>
          <Button
            data-testid="logout-button"
            onClick={onLogout}
            variant="ghost"
            className="rounded-sm hover:bg-slate-100"
          >
            <LogOut className="h-4 w-4 mr-2" />
            Déconnexion
          </Button>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        <Tabs defaultValue="users" className="space-y-6">
          <TabsList className="bg-white border border-slate-200">
            <TabsTrigger value="users" className="data-[state=active]:bg-slate-900 data-[state=active]:text-white">
              <Users className="h-4 w-4 mr-2" />
              Utilisateurs
            </TabsTrigger>
            <TabsTrigger value="webhooks" className="data-[state=active]:bg-slate-900 data-[state=active]:text-white">
              <Webhook className="h-4 w-4 mr-2" />
              Webhooks
            </TabsTrigger>
            <TabsTrigger value="general" className="data-[state=active]:bg-slate-900 data-[state=active]:text-white">
              <SettingsIcon className="h-4 w-4 mr-2" />
              Général
            </TabsTrigger>
          </TabsList>

          {/* Users Tab */}
          <TabsContent value="users">
            <Card className="border-slate-200 shadow-sm">
              <CardHeader>
                <CardTitle>Gestion des utilisateurs</CardTitle>
                <CardDescription>
                  Modifier les rôles et permissions des utilisateurs inscrits
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {users.map((u) => (
                    <div
                      key={u.id}
                      data-testid={`user-item-${u.id}`}
                      className="flex items-center justify-between p-4 bg-white border border-slate-200 rounded-sm"
                    >
                      <div className="flex-1">
                        <div className="flex items-center gap-3">
                          <div>
                            <p className="font-medium text-slate-900">{u.nom}</p>
                            <p className="text-sm text-slate-600">{u.email}</p>
                          </div>
                          <span className={`px-3 py-1 rounded-sm text-xs font-medium ${getRoleBadgeColor(u.role)}`}>
                            {u.role === "superviseur" ? "Superviseur" : u.role === "modification" ? "Modification" : "Consultation"}
                          </span>
                        </div>
                      </div>
                      <div className="w-48">
                        <Select
                          value={u.role}
                          onValueChange={(value) => handleRoleChange(u.id, value)}
                          disabled={u.email === "jfrancois.ouoba@gmail.com"}
                        >
                          <SelectTrigger data-testid={`role-select-${u.id}`} className="rounded-sm">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="consultation">Consultation</SelectItem>
                            <SelectItem value="modification">Modification</SelectItem>
                            <SelectItem value="superviseur">Superviseur</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Webhooks Tab */}
          <TabsContent value="webhooks">
            <Card className="border-slate-200 shadow-sm">
              <CardHeader>
                <CardTitle>Configuration des Webhooks</CardTitle>
                <CardDescription>
                  Définir les URLs des webhooks pour chaque événement
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {settings && Object.keys(settings.webhooks).map((event) => (
                    <div key={event} className="space-y-2">
                      <Label className="text-sm font-medium capitalize">
                        {event.replace("_", " ")}
                      </Label>
                      <Input
                        data-testid={`webhook-${event}`}
                        type="url"
                        value={settings.webhooks[event]}
                        onChange={(e) => setSettings({
                          ...settings,
                          webhooks: { ...settings.webhooks, [event]: e.target.value }
                        })}
                        placeholder={`https://api.example.com/webhooks/${event}`}
                        className="rounded-sm font-mono text-sm"
                      />
                    </div>
                  ))}
                  <div className="pt-4">
                    <Button
                      data-testid="save-webhooks-button"
                      onClick={handleSaveSettings}
                      disabled={saving}
                      className="rounded-sm bg-slate-900 hover:bg-slate-800"
                    >
                      <Save className="h-4 w-4 mr-2" />
                      {saving ? "Sauvegarde..." : "Sauvegarder"}
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* General Tab */}
          <TabsContent value="general">
            <Card className="border-slate-200 shadow-sm">
              <CardHeader>
                <CardTitle>Paramètres généraux</CardTitle>
                <CardDescription>
                  Configuration du site et de l'entreprise
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="site-title">Titre du site</Label>
                    <Input
                      id="site-title"
                      data-testid="site-title-input"
                      value={settings?.site_title || ""}
                      onChange={(e) => setSettings({ ...settings, site_title: e.target.value })}
                      className="rounded-sm"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="company-name">Nom de l'entreprise</Label>
                    <Input
                      id="company-name"
                      data-testid="company-name-input"
                      value={settings?.company_name || ""}
                      onChange={(e) => setSettings({ ...settings, company_name: e.target.value })}
                      className="rounded-sm"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="company-logo">URL du logo de l'entreprise</Label>
                    <Input
                      id="company-logo"
                      data-testid="company-logo-input"
                      type="url"
                      value={settings?.company_logo || ""}
                      onChange={(e) => setSettings({ ...settings, company_logo: e.target.value })}
                      placeholder="https://exemple.com/logo.png"
                      className="rounded-sm"
                    />
                  </div>

                  {settings?.company_logo && (
                    <div className="p-4 bg-slate-50 rounded-sm border border-slate-200">
                      <p className="text-sm text-slate-600 mb-2">Aperçu du logo :</p>
                      <img 
                        src={settings.company_logo} 
                        alt="Logo" 
                        className="h-16 object-contain"
                        onError={(e) => e.target.style.display = 'none'}
                      />
                    </div>
                  )}

                  <div className="pt-4">
                    <Button
                      data-testid="save-general-button"
                      onClick={handleSaveSettings}
                      disabled={saving}
                      className="rounded-sm bg-slate-900 hover:bg-slate-800"
                    >
                      <Save className="h-4 w-4 mr-2" />
                      {saving ? "Sauvegarde..." : "Sauvegarder"}
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}