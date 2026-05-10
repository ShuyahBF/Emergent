import { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { User, Mail, Phone, MessageCircle, Building2, Calendar, Clock, FileText, Activity, Users as UsersIcon, Send, Lock } from "lucide-react";

// Iter34k — Mon compte: read-only profile + request-change form
const Row = ({ icon: Icon, label, value, mono = false, testid }) => (
  <div className="flex items-start gap-3 py-2 border-b border-slate-100 last:border-0" data-testid={testid}>
    <Icon className="h-4 w-4 text-slate-400 mt-0.5 shrink-0" />
    <div className="flex-1 min-w-0">
      <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</p>
      <p className={`text-sm text-slate-800 ${mono ? "font-mono" : ""} ${value ? "" : "text-slate-300 italic"}`}>
        {value || "non renseigné"}
      </p>
    </div>
    <Lock className="h-3 w-3 text-slate-300 mt-1 shrink-0" title="Lecture seule — demander une modification ci-dessous" />
  </div>
);

const KpiCard = ({ icon: Icon, label, value, color }) => (
  <div className={`rounded-lg ring-1 ring-${color}-200 bg-${color}-50/60 p-3 text-center`} data-testid={`account-kpi-${label.toLowerCase()}`}>
    <Icon className={`h-5 w-5 mx-auto text-${color}-600 mb-1`} />
    <p className="text-2xl font-display font-bold text-slate-900">{value ?? 0}</p>
    <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</p>
  </div>
);

const FIELD_OPTIONS = [
  { id: "full_name", label: "Identité (nom & prénom)" },
  { id: "birth_date", label: "Date de naissance" },
  { id: "phone", label: "Numéro de téléphone" },
  { id: "whatsapp", label: "Numéro WhatsApp" },
  { id: "email", label: "Adresse email" },
  { id: "company", label: "Société / entreprise" },
];

export default function MyAccount() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedFields, setSelectedFields] = useState([]);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/account-detail");
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const toggle = (id) => {
    setSelectedFields((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]);
  };

  const submit = async () => {
    if (!message.trim()) { toast.error("Veuillez décrire la modification souhaitée"); return; }
    setSubmitting(true);
    try {
      await apiClient.post("/me/profile-update-request", {
        message: message.trim(),
        fields: selectedFields,
      });
      toast.success("Demande envoyée à l'administrateur");
      setMessage("");
      setSelectedFields([]);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSubmitting(false); }
  };

  const identity = data?.identity || {};
  const parent = data?.parent_client;
  const counters = data?.counters || {};

  const fmtDate = (iso) => {
    if (!iso) return null;
    try {
      return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
    } catch { return iso; }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6" data-testid="my-account-page">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold text-slate-900">Mon compte</h1>
          <p className="text-xs text-slate-500 mt-0.5">Informations de votre compte (lecture seule)</p>
        </div>
        {identity.avatar_url && (
          <img
            src={identity.avatar_url}
            alt="avatar"
            className="h-16 w-16 rounded-full ring-2 ring-sawali-blue/40 object-cover"
            data-testid="account-avatar"
          />
        )}
        {!identity.avatar_url && identity.full_name && (
          <div className="h-16 w-16 rounded-full ring-2 ring-sawali-blue/40 bg-gradient-to-br from-sawali-blue to-sawali-blue-light text-white text-2xl font-display font-bold flex items-center justify-center" data-testid="account-avatar-initials">
            {identity.full_name.split(" ").map((s) => s[0]).slice(0, 2).join("").toUpperCase()}
          </div>
        )}
      </header>

      {loading && !data && (
        <p className="text-center text-slate-400 py-8">Chargement…</p>
      )}

      {data && (
        <>
          {/* Identity */}
          <section className="rounded-xl ring-1 ring-slate-200 bg-white p-5" data-testid="account-identity-card">
            <h2 className="font-display font-semibold text-sm text-slate-700 mb-2 flex items-center gap-2">
              <User className="h-4 w-4 text-sawali-blue" /> Identité
            </h2>
            <div className="grid sm:grid-cols-2 gap-x-6">
              <Row icon={User} label="Nom complet" value={identity.full_name} testid="account-field-full-name" />
              <Row icon={Mail} label="Email" value={identity.email} mono testid="account-field-email" />
              <Row icon={Phone} label="Téléphone" value={identity.phone} mono testid="account-field-phone" />
              <Row icon={MessageCircle} label="WhatsApp" value={identity.whatsapp} mono testid="account-field-whatsapp" />
              <Row icon={Calendar} label="Date de naissance" value={identity.birth_date} testid="account-field-birth-date" />
              <Row icon={Lock} label="Rôle" value={identity.role} testid="account-field-role" />
            </div>
          </section>

          {/* Company / Parent client */}
          <section className="rounded-xl ring-1 ring-slate-200 bg-white p-5" data-testid="account-company-card">
            <h2 className="font-display font-semibold text-sm text-slate-700 mb-2 flex items-center gap-2">
              <Building2 className="h-4 w-4 text-sawali-blue" /> Société & rattachement
            </h2>
            <div className="grid sm:grid-cols-2 gap-x-6">
              <Row icon={Building2} label="Société (entreprise)" value={identity.company} testid="account-field-company" />
              <Row icon={UsersIcon} label="Client lié" value={parent ? `${parent.full_name || "—"}${parent.company ? ` — ${parent.company}` : ""}` : "Aucun (compte principal)"} testid="account-field-parent-client" />
            </div>
          </section>

          {/* Last seen */}
          <section className="rounded-xl ring-1 ring-amber-200 bg-amber-50/40 p-4" data-testid="account-last-seen">
            <div className="flex items-center gap-2 text-amber-700">
              <Clock className="h-4 w-4" />
              <p className="text-xs">
                <span className="font-semibold">Dernière connexion :</span>{" "}
                {data.last_seen_at ? <span data-testid="account-last-seen-value">{fmtDate(data.last_seen_at)}</span> : <span className="italic text-amber-600">Aucune connexion antérieure enregistrée</span>}
              </p>
            </div>
          </section>

          {/* Counters */}
          <section data-testid="account-counters">
            <h2 className="font-display font-semibold text-sm text-slate-700 mb-2">Activité associée à votre compte</h2>
            <div className="grid grid-cols-3 gap-3">
              <KpiCard icon={FileText} label="Rapports" value={counters.reports} color="sky" />
              <KpiCard icon={Activity} label="Suivis" value={counters.suivis} color="emerald" />
              <KpiCard icon={UsersIcon} label="Contacts" value={counters.contacts} color="amber" />
            </div>
            <p className="text-[10px] text-slate-400 mt-1 text-center">Les contacts visibles incluent ceux partagés par votre société.</p>
          </section>

          {/* Request modification */}
          <section className="rounded-xl ring-1 ring-indigo-200 bg-indigo-50/40 p-5" data-testid="account-request-section">
            <h2 className="font-display font-semibold text-sm text-indigo-800 mb-2 flex items-center gap-2">
              <Send className="h-4 w-4" /> Demande de modification
            </h2>
            <p className="text-xs text-slate-600 mb-3">
              Une faute d'orthographe, un changement de numéro, une date de naissance à corriger ? Décrivez votre demande, l'administrateur la traitera.
            </p>
            <div className="grid sm:grid-cols-2 gap-2 mb-3">
              {FIELD_OPTIONS.map((f) => (
                <label key={f.id} className="inline-flex items-center gap-2 text-xs text-slate-700 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={selectedFields.includes(f.id)}
                    onChange={() => toggle(f.id)}
                    data-testid={`request-field-${f.id}`}
                  />
                  {f.label}
                </label>
              ))}
            </div>
            <textarea
              rows={4}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              maxLength={1500}
              placeholder="Décrivez précisément la modification souhaitée (ex: 'Mon nom de famille s'écrit Diakité et non Diakite', 'Nouveau numéro WhatsApp : +225 07 XX XX XX XX', etc.)"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm resize-y"
              data-testid="request-message-input"
            />
            <div className="flex items-center justify-between mt-2">
              <span className="text-[10px] text-slate-400">{message.length}/1500</span>
              <button
                onClick={submit}
                disabled={submitting || !message.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 text-sm font-semibold disabled:opacity-50"
                data-testid="request-submit-btn"
              >
                <Send className="h-4 w-4" />
                {submitting ? "Envoi…" : "Envoyer à l'admin"}
              </button>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
