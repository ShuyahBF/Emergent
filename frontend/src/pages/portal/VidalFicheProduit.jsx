// Portage site-meetafrican (PR#14 "Fiche produit VIDAL") — recherche
// médicament → fiche produit réelle : voies d'administration + documents
// disponibles (RCP, monographie…) + bouton "Équivalences" (regroupement VMP
// officiel VIDAL). S'appuie sur les endpoints structurés de
// backend/routes/vidal_fiche.py (aucune donnée simulée, contrairement à la
// maquette d'origine).
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FileText, Loader2, Pill, Route as RouteIcon, ExternalLink, Layers } from "lucide-react";
import VidalMedicationSearch from "@/components/VidalMedicationSearch";
import { useVidalUiSettings } from "@/contexts/VidalUiSettingsContext";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

export default function VidalFicheProduit() {
  const { vidalAdminNotes } = useVidalUiSettings();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [product, setProduct] = useState(null); // {vidal_id, title}
  const [detail, setDetail] = useState(null); // {name, vmp_id, routes, documents}
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [equivalents, setEquivalents] = useState(null);
  const [loadingEquivalents, setLoadingEquivalents] = useState(false);

  const selectProduct = async (item) => {
    setProduct(item);
    setQuery("");
    setDetail(null);
    setEquivalents(null);
    if (!item.vidal_id) return;
    setLoadingDetail(true);
    try {
      const r = await apiClient.get(`/vidal/product/${item.vidal_id}/detail`);
      setDetail(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Fiche produit indisponible");
    }
    setLoadingDetail(false);
  };

  const loadEquivalents = async () => {
    if (!detail?.vmp_id) return;
    setLoadingEquivalents(true);
    try {
      const r = await apiClient.get(`/vidal/vmp/${detail.vmp_id}/equivalents`, {
        params: { exclude_product_id: product?.vidal_id },
      });
      setEquivalents(r.data?.equivalents || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Équivalences indisponibles");
    }
    setLoadingEquivalents(false);
  };

  const documentHref = (doc) =>
    doc.is_html ? doc.url : `${BACKEND}/api/vidal/documents/proxy?url=${encodeURIComponent(doc.url || "")}`;

  // Lot 15 — un document PDF réel (RCP, monographie…) s'ouvrait dans un
  // nouvel onglet via le lecteur PDF natif du navigateur : entièrement
  // copiable/téléchargeable. Remonté par l'utilisateur (capture + vidéo) ;
  // il a signalé que le lecteur interne non copiable existe déjà et sert à
  // "/portal/brochures" (PdfViewer.jsx : rendu par canvas, clic droit et
  // Ctrl+S bloqués pour les rôles non Admin/Superviseur). On réutilise EXACTEMENT
  // ce même lecteur ici plutôt que de laisser le navigateur ouvrir le PDF
  // brut. (Les pages VIDAL en HTML — is_html — ne sont pas des PDF et ne
  // peuvent pas passer par ce lecteur ; elles restent ouvertes normalement.)
  const openDocument = (doc) => {
    if (doc.is_html) {
      window.open(doc.url, "_blank", "noopener,noreferrer");
      return;
    }
    const src = documentHref(doc);
    const title = doc.title || doc.item_type;
    navigate(`/portal/brochures?src=${encodeURIComponent(src)}&title=${encodeURIComponent(title)}&kind=pdf`);
  };

  return (
    <div className="space-y-4" data-testid="vidal-fiche-page">
      <div className="flex items-center gap-3">
        {/* #BB2323 = même rouge que Sécurisation/Posologie (échantillonné sur
            capture réelle de la maquette d'origine), à la place du bleu
            générique — cohérence visuelle de tout le module VIDAL. */}
        <div className="w-10 h-10 rounded-lg bg-[#BB2323]/10 dark:bg-[#BB2323]/20 ring-1 ring-[#BB2323]/25 flex items-center justify-center">
          <Pill className="h-5 w-5 text-[#BB2323]" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-foreground">Fiche produit VIDAL</h1>
          <p className="text-xs text-muted-foreground">
            Recherchez un médicament pour voir ses voies d'administration, ses documents et ses équivalents.
          </p>
        </div>
      </div>

      <Card>
        <CardContent className="pt-6">
          <VidalMedicationSearch
            query={query}
            onQueryChange={setQuery}
            onSelect={selectProduct}
            onClear={() => setQuery("")}
            testId="fiche-search"
            placeholder="Rechercher un produit (ex : Efferalgan 500)…"
          />
        </CardContent>
      </Card>

      {loadingDetail && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="fiche-loading">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement de la fiche produit…
        </div>
      )}

      {detail && !loadingDetail && (
        <div className="grid gap-4 md:grid-cols-2" data-testid="fiche-detail">
          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Pill className="h-4 w-4 text-primary" /> {detail.name || product?.title}
                {product?.vidal_id && (
                  <span className="text-xs font-mono text-muted-foreground">#{product.vidal_id}</span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {detail.vmp_id ? (
                <Button size="sm" variant="outline" onClick={loadEquivalents} disabled={loadingEquivalents} data-testid="fiche-equivalents-btn">
                  {loadingEquivalents ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Layers className="h-3.5 w-3.5 mr-1.5" />}
                  Voir les équivalents (même DCI + dosage)
                </Button>
              ) : (
                <p className="text-xs text-muted-foreground">Aucun regroupement VMP renvoyé pour ce produit.</p>
              )}
              {equivalents && (
                <ul className="mt-3 space-y-1.5" data-testid="fiche-equivalents-list">
                  {equivalents.length === 0 && (
                    <li className="text-xs text-muted-foreground">Aucun produit équivalent trouvé.</li>
                  )}
                  {equivalents.map((eq, i) => (
                    <li key={eq.vidal_id || i} className="text-xs flex items-center justify-between rounded border px-2.5 py-1.5">
                      <span className="text-foreground">{eq.title}</span>
                      {eq.vidal_id && <span className="font-mono text-muted-foreground">#{eq.vidal_id}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <RouteIcon className="h-4 w-4" /> Voies d'administration
              </CardTitle>
            </CardHeader>
            <CardContent>
              {detail.routes?.length ? (
                <ul className="space-y-1" data-testid="fiche-routes-list">
                  {detail.routes.map((r) => (
                    <li key={r.id} className="text-xs flex items-center gap-2">
                      <Badge variant="outline">{r.name}</Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground">Aucune voie d'administration renvoyée par VIDAL.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <FileText className="h-4 w-4" /> Documents
              </CardTitle>
            </CardHeader>
            <CardContent>
              {detail.documents?.length ? (
                <ul className="space-y-1.5" data-testid="fiche-documents-list">
                  {detail.documents.map((doc) => (
                    <li key={doc.item_type} className="text-xs">
                      <button
                        type="button"
                        onClick={() => openDocument(doc)}
                        className="inline-flex items-center gap-1.5 text-primary hover:underline"
                        data-testid={`fiche-document-${doc.item_type}`}
                      >
                        {doc.title || doc.item_type}
                        <ExternalLink className="h-3 w-3" />
                      </button>
                      <Badge variant={doc.is_html ? "secondary" : "outline"} className="ml-2 text-[10px]">
                        {doc.is_html ? "VIDAL (intégré)" : "Lecteur interne"}
                      </Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground">Aucun document renvoyé par VIDAL pour ce produit.</p>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {vidalAdminNotes && (
        <Card className="border-dashed" data-testid="fiche-admin-notes">
          <CardContent className="pt-6 text-xs text-muted-foreground space-y-1">
            <p className="font-semibold text-foreground">Notes VIDAL (admin)</p>
            <p>
              La fiche produit provient d'un seul appel agrégé
              <code className="mx-1 px-1 rounded bg-muted">GET /product/{"{id}"}?aggregate=ROUTE&amp;aggregate=DOCUMENTS</code>
              (confirmé par test réel côté maquette site-meetafrican).
            </p>
            <p>
              Les documents non-HTML (RCP en PDF notamment) transitent par
              <code className="mx-1 px-1 rounded bg-muted">/api/vidal/documents/proxy</code>
              car certains hôtes VIDAL renvoient <code className="px-1 rounded bg-muted">X-Frame-Options: SAMEORIGIN</code>.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
