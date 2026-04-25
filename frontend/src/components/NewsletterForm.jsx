import React, { useState } from "react";
import { Send, Mail, CheckCircle2 } from "lucide-react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";

export default function NewsletterForm() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const r = await apiClient.post("/newsletter/subscribe", { email, name, source: "footer" });
      setDone(true);
      toast.success(r.data.message || "Inscription confirmée");
      setEmail(""); setName("");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'inscription");
    } finally { setLoading(false); }
  };

  return (
    <form onSubmit={submit} className="space-y-2" data-testid="newsletter-form">
      <p className="text-xs text-slate-400">Recevez nos articles techniques et études de cas, chaque mois.</p>
      <div className="flex flex-col sm:flex-row gap-2">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Prénom (optionnel)"
          className="flex-1 rounded-md bg-white/5 border border-white/10 text-white placeholder:text-slate-500 px-3 py-2 text-sm focus:outline-none focus:border-sawali-blue"
          data-testid="newsletter-name"
        />
      </div>
      <div className="flex gap-2">
        <div className="flex-1 relative">
          <Mail className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-500" />
          <input
            required
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="vous@email.com"
            className="w-full rounded-md bg-white/5 border border-white/10 text-white placeholder:text-slate-500 pl-8 pr-3 py-2 text-sm focus:outline-none focus:border-sawali-blue"
            data-testid="newsletter-email"
          />
        </div>
        <button type="submit" disabled={loading} className="btn-electric inline-flex items-center gap-1 rounded-md px-3 py-2 text-sm disabled:opacity-50" data-testid="newsletter-submit">
          {done ? <CheckCircle2 className="h-4 w-4" /> : <Send className="h-4 w-4" />}
          <span className="hidden sm:inline">{done ? "Inscrit" : "S'abonner"}</span>
        </button>
      </div>
    </form>
  );
}
