import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowLeft, LogOut } from "lucide-react";
import JustificationModal from "@/components/JustificationModal";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function DocumentViewer({ user, onLogout }) {
  const { documentId } = useParams();
  const navigate = useNavigate();
  const [document, setDocument] = useState(null);
  const [lines, setLines] = useState([]);
  const [selectedLine, setSelectedLine] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDocumentData();
  }, [documentId]);

  const fetchDocumentData = async () => {
    try {
      const token = localStorage.getItem("token");
      
      const [docResponse, linesResponse] = await Promise.all([
        axios.get(`${API}/documents/${documentId}`, {
          headers: { Authorization: `Bearer ${token}` }
        }),
        axios.get(`${API}/documents/${documentId}/lines`, {
          headers: { Authorization: `Bearer ${token}` }
        })
      ]);

      setDocument(docResponse.data);
      setLines(linesResponse.data);
    } catch (error) {
      toast.error("Erreur lors du chargement du document");
      navigate("/");
    } finally {
      setLoading(false);
    }
  };

  const formatAmount = (amount) => {
    return new Intl.NumberFormat('fr-FR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(amount);
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
              <h1 className="text-lg font-bold text-slate-900">{document?.filename}</h1>
              <p className="text-xs text-slate-600">{lines.length} lignes comptables</p>
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
        <Card className="border-slate-200 shadow-sm">
          <CardHeader>
            <CardTitle>Lignes comptables</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200">
                    <th className="text-left p-4 text-xs font-medium text-slate-600 uppercase tracking-wider">Ligne</th>
                    <th className="text-left p-4 text-xs font-medium text-slate-600 uppercase tracking-wider">N° Compte</th>
                    <th className="text-left p-4 text-xs font-medium text-slate-600 uppercase tracking-wider">Intitulé</th>
                    <th className="text-right p-4 text-xs font-medium text-slate-600 uppercase tracking-wider">Débit</th>
                    <th className="text-right p-4 text-xs font-medium text-slate-600 uppercase tracking-wider">Crédit</th>
                    <th className="text-right p-4 text-xs font-medium text-slate-600 uppercase tracking-wider">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line) => (
                    <tr
                      key={line.id}
                      data-testid={`line-row-${line.id}`}
                      className="border-b border-slate-200 table-row-hover"
                      onClick={() => setSelectedLine(line)}
                    >
                      <td className="p-4 font-mono text-sm text-slate-900">{line.line_number}</td>
                      <td className="p-4 font-mono text-sm text-slate-900">{line.account_number}</td>
                      <td className="p-4 text-sm text-slate-900">{line.label}</td>
                      <td className="p-4 text-right font-mono text-sm text-slate-900">
                        {line.debit > 0 ? formatAmount(line.debit) : '-'}
                      </td>
                      <td className="p-4 text-right font-mono text-sm text-slate-900">
                        {line.credit > 0 ? formatAmount(line.credit) : '-'}
                      </td>
                      <td className="p-4 text-right font-mono text-sm font-medium text-slate-900">
                        {formatAmount(line.total)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </main>

      {/* Justification Modal */}
      {selectedLine && (
        <JustificationModal
          line={selectedLine}
          onClose={() => setSelectedLine(null)}
        />
      )}
    </div>
  );
}