import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Upload, FileText, LogOut, Calendar, CheckCircle2, Settings } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function Dashboard({ user, onLogout }) {
  const [documents, setDocuments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    fetchDocuments();
  }, []);

  const fetchDocuments = async () => {
    try {
      const token = localStorage.getItem("token");
      const response = await axios.get(`${API}/documents`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setDocuments(response.data);
    } catch (error) {
      toast.error("Erreur lors du chargement des documents");
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.pdf')) {
      toast.error("Seuls les fichiers PDF sont acceptés");
      return;
    }

    setUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const token = localStorage.getItem("token");
      const response = await axios.post(`${API}/documents`, formData, {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "multipart/form-data"
        }
      });

      toast.success("Document uploadé et traité avec succès");
      setDocuments([response.data, ...documents]);
    } catch (error) {
      const message = error.response?.data?.detail || "Erreur lors de l'upload";
      toast.error(message);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleDateString('fr-FR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="sticky top-0 z-50 backdrop-blur-md bg-white/80 border-b border-slate-200 h-16">
        <div className="max-w-7xl mx-auto px-6 h-full flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Justification Comptable</h1>
            <p className="text-xs text-slate-600">Bienvenue, {user.nom}</p>
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
        {/* Upload Section */}
        <Card className="mb-8 border-slate-200 shadow-sm hover-lift">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Upload className="h-5 w-5" />
              Uploader un nouveau document PDF
            </CardTitle>
            <CardDescription>
              Importez vos fichiers PDF contenant les lignes comptables à justifier
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-4">
              <Input
                data-testid="file-upload-input"
                type="file"
                accept=".pdf"
                onChange={handleFileUpload}
                disabled={uploading}
                className="rounded-sm cursor-pointer"
              />
              {uploading && (
                <div className="flex items-center gap-2 text-sm text-slate-600">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-slate-900"></div>
                  Traitement en cours...
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Documents List */}
        <div>
          <h2 className="text-2xl font-bold mb-6 text-slate-900">Mes documents</h2>
          
          {loading ? (
            <div className="flex justify-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-slate-900"></div>
            </div>
          ) : documents.length === 0 ? (
            <Card className="border-slate-200">
              <CardContent className="py-12 text-center">
                <FileText className="h-16 w-16 mx-auto mb-4 text-slate-300" />
                <p className="text-slate-600">Aucun document. Uploadez votre premier fichier PDF.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {documents.map((doc) => (
                <Card
                  key={doc.id}
                  data-testid={`document-card-${doc.id}`}
                  className="border-slate-200 shadow-sm hover-lift cursor-pointer transition-all"
                  onClick={() => navigate(`/documents/${doc.id}`)}
                >
                  <CardHeader>
                    <div className="flex items-start justify-between">
                      <FileText className="h-10 w-10 text-slate-700" />
                      <span className="inline-flex items-center gap-1 px-2 py-1 rounded-sm bg-green-50 text-green-700 text-xs font-medium">
                        <CheckCircle2 className="h-3 w-3" />
                        {doc.status === 'processed' ? 'Traité' : doc.status}
                      </span>
                    </div>
                    <CardTitle className="text-base mt-4 truncate" title={doc.filename}>
                      {doc.filename}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2 text-sm">
                      <div className="flex items-center gap-2 text-slate-600">
                        <Calendar className="h-4 w-4" />
                        {formatDate(doc.upload_date)}
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-slate-600">Lignes comptables:</span>
                        <span className="font-mono font-medium text-slate-900">{doc.total_lines}</span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}