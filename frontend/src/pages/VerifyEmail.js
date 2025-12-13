import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function VerifyEmail() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState("loading"); // loading, success, error
  const [message, setMessage] = useState("");

  useEffect(() => {
    verifyEmail();
  }, [token]);

  const verifyEmail = async () => {
    try {
      const response = await axios.get(`${API}/auth/verify-email/${token}`);
      setStatus("success");
      setMessage(response.data.message);
    } catch (error) {
      setStatus("error");
      setMessage(error.response?.data?.detail || "Erreur lors de la vérification de l'email");
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-4">
      <Card className="w-full max-w-md shadow-lg border-slate-200">
        <CardHeader className="text-center">
          {status === "loading" && (
            <>
              <Loader2 className="h-16 w-16 animate-spin mx-auto mb-4 text-slate-600" />
              <CardTitle>Vérification en cours...</CardTitle>
              <CardDescription>Veuillez patienter</CardDescription>
            </>
          )}
          {status === "success" && (
            <>
              <CheckCircle2 className="h-16 w-16 mx-auto mb-4 text-green-600" />
              <CardTitle className="text-green-600">Email vérifié !</CardTitle>
              <CardDescription>{message}</CardDescription>
            </>
          )}
          {status === "error" && (
            <>
              <XCircle className="h-16 w-16 mx-auto mb-4 text-red-600" />
              <CardTitle className="text-red-600">Erreur</CardTitle>
              <CardDescription>{message}</CardDescription>
            </>
          )}
        </CardHeader>
        <CardContent className="text-center">
          {status === "success" && (
            <Button
              onClick={() => navigate("/login")}
              className="w-full rounded-sm bg-slate-900 hover:bg-slate-800"
            >
              Se connecter
            </Button>
          )}
          {status === "error" && (
            <Button
              onClick={() => navigate("/login")}
              variant="outline"
              className="w-full rounded-sm"
            >
              Retour à la connexion
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}