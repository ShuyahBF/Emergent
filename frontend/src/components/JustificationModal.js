import { useState, useEffect } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Plus, Trash2, Save, CheckCircle2, AlertCircle } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function JustificationModal({ line, user, onClose }) {
  const [details, setDetails] = useState([]);
  const [justificationId, setJustificationId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchJustification();
  }, [line.id]);

  const fetchJustification = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem("token");
      const response = await axios.get(`${API}/lines/${line.id}/justifications`, {
        headers: { Authorization: `Bearer ${token}` }
      });

      if (response.data) {
        setDetails(response.data.details || []);
        setJustificationId(response.data.id);
      } else {
        // Initialize with one empty line
        setDetails([{ label: "", debit: 0, credit: 0 }]);
      }
    } catch (error) {
      console.error("Error fetching justification:", error);
      setDetails([{ label: "", debit: 0, credit: 0 }]);
    } finally {
      setLoading(false);
    }
  };

  const addDetail = () => {
    setDetails([...details, { label: "", debit: 0, credit: 0 }]);
  };

  const removeDetail = (index) => {
    if (details.length > 1) {
      setDetails(details.filter((_, i) => i !== index));
    }
  };

  const updateDetail = (index, field, value) => {
    const newDetails = [...details];
    newDetails[index] = {
      ...newDetails[index],
      [field]: field === "label" ? value : parseFloat(value) || 0
    };
    setDetails(newDetails);
  };

  const calculateTotals = () => {
    const totalDebit = details.reduce((sum, d) => sum + (d.debit || 0), 0);
    const totalCredit = details.reduce((sum, d) => sum + (d.credit || 0), 0);
    return { totalDebit, totalCredit };
  };

  const isValid = () => {
    const { totalDebit, totalCredit } = calculateTotals();
    return (
      Math.abs(totalDebit - line.debit) < 0.01 &&
      Math.abs(totalCredit - line.credit) < 0.01
    );
  };

  const handleSave = async () => {
    if (details.some(d => !d.label.trim())) {
      toast.error("Tous les intitulés doivent être remplis");
      return;
    }

    setSaving(true);
    try {
      const token = localStorage.getItem("token");
      const payload = { details };

      if (justificationId) {
        // Update existing
        await axios.put(`${API}/justifications/${justificationId}`, payload, {
          headers: { Authorization: `Bearer ${token}` }
        });
      } else {
        // Create new
        const response = await axios.post(`${API}/lines/${line.id}/justifications`, payload, {
          headers: { Authorization: `Bearer ${token}` }
        });
        setJustificationId(response.data.id);
      }

      toast.success("Justification sauvegardée");
    } catch (error) {
      const message = error.response?.data?.detail || "Erreur lors de la sauvegarde";
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  const formatAmount = (amount) => {
    return new Intl.NumberFormat('fr-FR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(amount);
  };

  const { totalDebit, totalCredit } = calculateTotals();
  const validated = isValid();

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto" data-testid="justification-modal">
        <DialogHeader>
          <DialogTitle className="text-xl">Justification de la ligne comptable</DialogTitle>
          <DialogDescription>
            N° Compte: <span className="font-mono font-medium">{line.account_number}</span> - {line.label}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-slate-900"></div>
          </div>
        ) : (
          <div className="space-y-6">
            {/* Original Line Summary */}
            <div className="bg-slate-50 p-4 rounded-sm border border-slate-200">
              <h3 className="text-sm font-medium mb-2 text-slate-700">Ligne originale</h3>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-slate-600">Débit: </span>
                  <span className="font-mono font-medium">{formatAmount(line.debit)}</span>
                </div>
                <div>
                  <span className="text-slate-600">Crédit: </span>
                  <span className="font-mono font-medium">{formatAmount(line.credit)}</span>
                </div>
                <div>
                  <span className="text-slate-600">Total: </span>
                  <span className="font-mono font-medium">{formatAmount(line.total)}</span>
                </div>
              </div>
            </div>

            {/* Details Table */}
            <div>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-medium text-slate-700">Détails de justification</h3>
                <Button
                  data-testid="add-detail-button"
                  onClick={addDetail}
                  size="sm"
                  variant="outline"
                  className="rounded-sm"
                >
                  <Plus className="h-4 w-4 mr-2" />
                  Ajouter une ligne
                </Button>
              </div>

              <div className="space-y-3">
                {details.map((detail, index) => (
                  <div
                    key={index}
                    data-testid={`detail-row-${index}`}
                    className="flex gap-3 items-start p-3 bg-white border border-slate-200 rounded-sm"
                  >
                    <div className="flex-1">
                      <Label className="text-xs text-slate-600 mb-1">Intitulé</Label>
                      <Input
                        data-testid={`detail-label-${index}`}
                        value={detail.label}
                        onChange={(e) => updateDetail(index, "label", e.target.value)}
                        placeholder="Description de la pièce"
                        className="rounded-sm"
                      />
                    </div>
                    <div className="w-32">
                      <Label className="text-xs text-slate-600 mb-1">Débit</Label>
                      <Input
                        data-testid={`detail-debit-${index}`}
                        type="number"
                        step="0.01"
                        value={detail.debit}
                        onChange={(e) => updateDetail(index, "debit", e.target.value)}
                        className="rounded-sm font-mono text-right"
                      />
                    </div>
                    <div className="w-32">
                      <Label className="text-xs text-slate-600 mb-1">Crédit</Label>
                      <Input
                        data-testid={`detail-credit-${index}`}
                        type="number"
                        step="0.01"
                        value={detail.credit}
                        onChange={(e) => updateDetail(index, "credit", e.target.value)}
                        className="rounded-sm font-mono text-right"
                      />
                    </div>
                    <Button
                      data-testid={`remove-detail-${index}`}
                      onClick={() => removeDetail(index)}
                      variant="ghost"
                      size="sm"
                      className="mt-6 rounded-sm hover:bg-red-50 hover:text-red-600"
                      disabled={details.length === 1}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>

            {/* Totals and Validation */}
            <div className="bg-slate-50 p-4 rounded-sm border border-slate-200">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-slate-700">Totaux calculés</h3>
                <div className="flex items-center gap-2">
                  {validated ? (
                    <span className="inline-flex items-center gap-1 px-3 py-1 rounded-sm bg-green-50 text-green-700 text-xs font-medium">
                      <CheckCircle2 className="h-4 w-4" />
                      Validé
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-3 py-1 rounded-sm bg-amber-50 text-amber-700 text-xs font-medium">
                      <AlertCircle className="h-4 w-4" />
                      Non validé
                    </span>
                  )}
                </div>
              </div>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-slate-600">Total Débit: </span>
                  <span className={`font-mono font-medium ${Math.abs(totalDebit - line.debit) < 0.01 ? 'text-green-600' : 'text-red-600'}`}>
                    {formatAmount(totalDebit)}
                  </span>
                </div>
                <div>
                  <span className="text-slate-600">Total Crédit: </span>
                  <span className={`font-mono font-medium ${Math.abs(totalCredit - line.credit) < 0.01 ? 'text-green-600' : 'text-red-600'}`}>
                    {formatAmount(totalCredit)}
                  </span>
                </div>
                <div>
                  <span className="text-slate-600">Différence: </span>
                  <span className="font-mono font-medium">
                    {formatAmount(Math.abs((totalDebit - line.debit) + (totalCredit - line.credit)))}
                  </span>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="flex justify-end gap-3">
              <Button
                data-testid="cancel-button"
                onClick={onClose}
                variant="outline"
                className="rounded-sm"
              >
                Annuler
              </Button>
              <Button
                data-testid="save-button"
                onClick={handleSave}
                disabled={saving}
                className="rounded-sm bg-slate-900 hover:bg-slate-800 active:scale-95 transition-all"
              >
                {saving ? (
                  "Sauvegarde..."
                ) : (
                  <>
                    <Save className="h-4 w-4 mr-2" />
                    Sauvegarder
                  </>
                )}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}