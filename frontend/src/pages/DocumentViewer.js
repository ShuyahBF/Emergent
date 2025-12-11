import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ArrowLeft, LogOut, Edit2, Save, X } from "lucide-react";
import JustificationModal from "@/components/JustificationModal";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function DocumentViewer({ user, onLogout }) {
  const { documentId } = useParams();
  const navigate = useNavigate();
  const [document, setDocument] = useState(null);
  const [lines, setLines] = useState([]);
  const [selectedLine, setSelectedLine] = useState(null);
  const [editingLine, setEditingLine] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

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

  const startEdit = (line) => {
    if (user.role !== "modification" && user.role !== "superviseur") {
      toast.error("Vous n'avez pas la permission de modifier");
      return;
    }
    setEditingLine(line.id);
    setEditForm({
      label: line.label,
      debit: line.debit,
      credit: line.credit
    });
  };

  const cancelEdit = () => {
    setEditingLine(null);
    setEditForm({});
  };

  const saveEdit = async (lineId) => {
    setSaving(true);
    try {
      const token = localStorage.getItem("token");
      await axios.put(`${API}/lines/${lineId}`, editForm, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success("Ligne mise à jour");
      setEditingLine(null);
      setEditForm({});
      fetchDocumentData();
    } catch (error) {
      toast.error("Erreur lors de la mise à jour");
    } finally {
      setSaving(false);
    }
  };

  const handleDebitChange = (value) => {
    const debitValue = parseFloat(value) || 0;
    setEditForm({
      ...editForm,
      debit: debitValue,
      credit: 0
    });
  };

  const handleCreditChange = (value) => {
    const creditValue = parseFloat(value) || 0;
    setEditForm({
      ...editForm,
      credit: creditValue,
      debit: 0
    });
  };

  const formatAmount = (amount) => {
    return new Intl.NumberFormat('fr-FR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(amount);
  };

  const canEdit = user.role === "modification" || user.role === "superviseur";

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
                    <th className="text-right p-4 text-xs font-medium text-slate-600 uppercase tracking-wider">Justification</th>
                    {canEdit && (
                      <th className="text-center p-4 text-xs font-medium text-slate-600 uppercase tracking-wider">Actions</th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line) => (
                    <tr
                      key={line.id}
                      data-testid={`line-row-${line.id}`}
                      className="border-b border-slate-200 hover:bg-slate-50 transition-colors"
                    >
                      <td className="p-4 font-mono text-sm text-slate-900">{line.line_number}</td>
                      <td className="p-4 font-mono text-sm text-slate-900">{line.account_number}</td>
                      
                      {/* Label */}
                      <td className="p-4 text-sm text-slate-900">
                        {editingLine === line.id ? (
                          <Input
                            data-testid={`edit-label-${line.id}`}
                            value={editForm.label}
                            onChange={(e) => setEditForm({ ...editForm, label: e.target.value })}
                            className="rounded-sm"
                          />
                        ) : (
                          <span onClick={() => setSelectedLine(line)} className="cursor-pointer">
                            {line.label}
                          </span>
                        )}
                      </td>
                      
                      {/* Debit */}
                      <td className="p-4 text-right font-mono text-sm text-slate-900">
                        {editingLine === line.id ? (
                          <Input
                            data-testid={`edit-debit-${line.id}`}
                            type="number"
                            step="0.01"
                            value={editForm.debit}
                            onChange={(e) => handleDebitChange(e.target.value)}
                            className="rounded-sm text-right"
                          />
                        ) : (
                          <span onClick={() => setSelectedLine(line)} className="cursor-pointer">
                            {line.debit > 0 ? formatAmount(line.debit) : '-'}
                          </span>
                        )}
                      </td>
                      
                      {/* Credit */}
                      <td className="p-4 text-right font-mono text-sm text-slate-900">
                        {editingLine === line.id ? (
                          <Input
                            data-testid={`edit-credit-${line.id}`}
                            type="number"
                            step="0.01"
                            value={editForm.credit}
                            onChange={(e) => handleCreditChange(e.target.value)}
                            className="rounded-sm text-right"
                          />
                        ) : (
                          <span onClick={() => setSelectedLine(line)} className="cursor-pointer">
                            {line.credit > 0 ? formatAmount(line.credit) : '-'}
                          </span>
                        )}
                      </td>
                      
                      {/* Calculated Total (from justifications) */}
                      <td className="p-4 text-right font-mono text-sm font-medium text-slate-900">
                        <span onClick={() => setSelectedLine(line)} className="cursor-pointer">
                          {line.calculated_total > 0 ? formatAmount(line.calculated_total) : '-'}
                        </span>
                      </td>
                      
                      {/* Actions */}
                      {canEdit && (
                        <td className="p-4 text-center">
                          {editingLine === line.id ? (
                            <div className="flex items-center justify-center gap-2">
                              <Button
                                data-testid={`save-edit-${line.id}`}
                                onClick={() => saveEdit(line.id)}
                                disabled={saving}
                                size="sm"
                                className="rounded-sm bg-green-600 hover:bg-green-700 h-8 px-3"
                              >
                                <Save className="h-3 w-3" />
                              </Button>
                              <Button
                                data-testid={`cancel-edit-${line.id}`}
                                onClick={cancelEdit}
                                size="sm"
                                variant="ghost"
                                className="rounded-sm h-8 px-3"
                              >
                                <X className="h-3 w-3" />
                              </Button>
                            </div>
                          ) : (
                            <Button
                              data-testid={`edit-line-${line.id}`}
                              onClick={() => startEdit(line)}
                              size="sm"
                              variant="ghost"
                              className="rounded-sm h-8 px-3"
                            >
                              <Edit2 className="h-3 w-3" />
                            </Button>
                          )}
                        </td>
                      )}
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
          user={user}
          onClose={() => {
            setSelectedLine(null);
            fetchDocumentData();
          }}
        />
      )}
    </div>
  );
}
