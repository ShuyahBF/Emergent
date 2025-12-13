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
import { ArrowLeft, LogOut, Save, Users, Settings as SettingsIcon, Webhook, UserCheck, UserX, Trash2, CheckCircle2, XCircle } from "lucide-react";

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

  const handleActivateUser = async (userId) => {
    try {
      const token = localStorage.getItem("token");
      await axios.post(`${API}/users/${userId}/activate`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success("Compte activé");
      fetchData();
    } catch (error) {
      toast.error("Erreur lors de l'activation");
    }
  };

  const handleDeactivateUser = async (userId) => {
    try {
      const token = localStorage.getItem("token");
      await axios.post(`${API}/users/${userId}/deactivate`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success("Compte désactivé");
      fetchData();
    } catch (error) {
      toast.error("Erreur lors de la désactivation");
    }
  };

  const handleDeleteUser = async (userId) => {
    if (!window.confirm("Êtes-vous sûr de vouloir désactiver ce compte ?")) {
      return;
    }
    try {
      const token = localStorage.getItem("token");
      await axios.delete(`${API}/users/${userId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success("Compte désactivé");
      fetchData();
    } catch (error) {
      toast.error("Erreur lors de la suppression");
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

  const formatDateTime = (dateString) => {
    if (!dateString) return "Jamais";
    return new Date(dateString).toLocaleString('fr-FR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
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
                  Modifier les rôles, activer/désactiver les comptes
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-slate-200">
                        <th className="text-left p-3 text-xs font-medium text-slate-600 uppercase">Nom</th>
                        <th className="text-left p-3 text-xs font-medium text-slate-600 uppercase">Email</th>
                        <th className="text-left p-3 text-xs font-medium text-slate-600 uppercase">Rôle</th>
                        <th className="text-center p-3 text-xs font-medium text-slate-600 uppercase">Email vérifié</th>
                        <th className="text-left p-3 text-xs font-medium text-slate-600 uppercase">Dernière connexion</th>
                        <th className="text-center p-3 text-xs font-medium text-slate-600 uppercase">Statut</th>
                        <th className="text-center p-3 text-xs font-medium text-slate-600 uppercase">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((u) => (
                        <tr
                          key={u.id}
                          data-testid={`user-row-${u.id}`}
                          className="border-b border-slate-200"
                        >
                          <td className="p-3 text-sm font-medium text-slate-900">{u.nom}</td>
                          <td className="p-3 text-sm text-slate-600">{u.email}</td>
                          <td className="p-3">
                            <Select
                              value={u.role}
                              onValueChange={(value) => handleRoleChange(u.id, value)}
                              disabled={u.email === "jfrancois.ouoba@gmail.com"}
                            >
                              <SelectTrigger data-testid={`role-select-${u.id}`} className="rounded-sm w-40">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="consultation">Consultation</SelectItem>
                                <SelectItem value="modification">Modification</SelectItem>
                                <SelectItem value="superviseur">Superviseur</SelectItem>
                              </SelectContent>
                            </Select>
                          </td>
                          <td className="p-3 text-center">
                            {u.email_verified ? (
                              <CheckCircle2 className="h-5 w-5 text-green-600 mx-auto" />
                            ) : (
                              <XCircle className="h-5 w-5 text-red-600 mx-auto" />
                            )}
                          </td>
                          <td className="p-3 text-sm text-slate-600">
                            {formatDateTime(u.last_login)}
                          </td>
                          <td className="p-3 text-center">
                            <span className={`inline-block px-2 py-1 rounded-sm text-xs font-medium ${
                              u.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                            }`}>
                              {u.is_active ? 'Actif' : 'Inactif'}
                            </span>
                          </td>
                          <td className="p-3">
                            <div className="flex items-center justify-center gap-2">
                              {u.is_active ? (
                                <Button
                                  data-testid={`deactivate-${u.id}`}
                                  onClick={() => handleDeactivateUser(u.id)}
                                  size="sm"
                                  variant="ghost"
                                  className="rounded-sm hover:bg-orange-50 hover:text-orange-600"
                                  title="Désactiver"
                                >
                                  <UserX className="h-4 w-4" />
                                </Button>
                              ) : (
                                <Button
                                  data-testid={`activate-${u.id}`}
                                  onClick={() => handleActivateUser(u.id)}
                                  size="sm"
                                  variant="ghost"
                                  className="rounded-sm hover:bg-green-50 hover:text-green-600"
                                  title="Activer"
                                >
                                  <UserCheck className="h-4 w-4" />
                                </Button>
                              )}
                              <Button
                                data-testid={`delete-${u.id}`}
                                onClick={() => handleDeleteUser(u.id)}
                                size="sm"
                                variant="ghost"
                                className="rounded-sm hover:bg-red-50 hover:text-red-600"
                                title="Supprimer (désactive le compte)"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
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
            <div className="space-y-6">
              {/* Configuration Générale */}
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
                  </div>
                </CardContent>
              </Card>

              {/* Configuration SMTP */}
              <Card className="border-slate-200 shadow-sm">
                <CardHeader>
                  <CardTitle>Configuration SMTP (Gmail)</CardTitle>
                  <CardDescription>
                    Paramètres pour l'envoi d'emails de vérification
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="frontend-url">URL du site frontend</Label>
                      <Input
                        id="frontend-url"
                        data-testid="frontend-url-input"
                        value={settings?.frontend_url || ""}
                        onChange={(e) => setSettings({ ...settings, frontend_url: e.target.value })}
                        placeholder="https://votre-site.com"
                        className="rounded-sm"
                      />
                      <p className="text-xs text-slate-500">URL utilisée dans les liens de vérification d'email</p>
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="smtp-host">Hôte SMTP</Label>
                      <Input
                        id="smtp-host"
                        data-testid="smtp-host-input"
                        value={settings?.smtp_host || "smtp.gmail.com"}
                        onChange={(e) => setSettings({ ...settings, smtp_host: e.target.value })}
                        className="rounded-sm"
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="smtp-port">Port SMTP</Label>
                      <Input
                        id="smtp-port"
                        data-testid="smtp-port-input"
                        type="number"
                        value={settings?.smtp_port || 587}
                        onChange={(e) => setSettings({ ...settings, smtp_port: parseInt(e.target.value) })}
                        className="rounded-sm"
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="smtp-user">Email SMTP (Gmail)</Label>
                      <Input
                        id="smtp-user"
                        data-testid="smtp-user-input"
                        type="email"
                        value={settings?.smtp_user || ""}
                        onChange={(e) => setSettings({ ...settings, smtp_user: e.target.value })}
                        placeholder="votre-email@gmail.com"
                        className="rounded-sm"
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="smtp-password">Mot de passe d'application Gmail</Label>
                      <Input
                        id="smtp-password"
                        data-testid="smtp-password-input"
                        type="password"
                        value={settings?.smtp_password || ""}
                        onChange={(e) => setSettings({ ...settings, smtp_password: e.target.value })}
                        placeholder="••••••••••••••••"
                        className="rounded-sm"
                      />
                      <p className="text-xs text-slate-500">
                        Utilisez un mot de passe d'application Gmail (pas votre mot de passe principal).
                        <a href="https://support.google.com/accounts/answer/185833" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline ml-1">
                          Comment créer un mot de passe d'application ?
                        </a>
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Bouton Sauvegarder */}
              <div className="flex justify-end">
                <Button
                  data-testid="save-general-button"
                  onClick={handleSaveSettings}
                  disabled={saving}
                  className="rounded-sm bg-slate-900 hover:bg-slate-800"
                >
                  <Save className="h-4 w-4 mr-2" />
                  {saving ? "Sauvegarde..." : "Sauvegarder tous les paramètres"}
                </Button>
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
