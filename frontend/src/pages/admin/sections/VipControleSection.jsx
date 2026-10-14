// =====================================================================
// Lot 158 — Rubrique des Paramètres « 💬 Ligne VIP — contrat valide » : la ligne « Liluvine VIP » est réservée aux clients
// dont le contrat est valide (puce verte du Centre de messagerie). Réglages enregistrés directement (bouton propre) :
//   GET / PUT /api/admin/whatsapp/vip-controle  { actif, message, notification }
// - message      : texte envoyé au client qui écrit sur la ligne VIP sans contrat valide (envoyé une fois toutes les 6 h) ;
// - notification : texte montré à l'agent quand sa réponse est forcée sur la ligne standard.
// Texte vide = texte par défaut. Désactivé par défaut : tant qu'il ne l'est pas, rien ne change.
// =====================================================================
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function VipControleSection() {
  const [etat, setEtat] = useState(null);                  // réponse du serveur (valeurs et textes par défaut)
  const [actif, setActif] = useState(false);
  const [message, setMessage] = useState("");
  const [notification, setNotification] = useState("");
  const [occupe, setOccupe] = useState(false);

  // Lecture des réglages enregistrés
  useEffect(() => {
    apiClient.get("/admin/whatsapp/vip-controle").then((r) => {
      setEtat(r.data); setActif(!!r.data.actif); setMessage(r.data.message || ""); setNotification(r.data.notification || "");
    }).catch(() => toast.error("Réglages de la ligne VIP illisibles"));
  }, []);

  // Enregistrement des trois réglages
  const enregistrer = async () => {
    setOccupe(true);
    try {
      const { data } = await apiClient.put("/admin/whatsapp/vip-controle", { actif, message, notification });
      setEtat(data); setMessage(data.message || ""); setNotification(data.notification || "");
      toast.success("Réglages de la ligne VIP enregistrés");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Enregistrement impossible");
    } finally { setOccupe(false); }
  };

  if (!etat) return <p className="text-sm text-slate-500">Chargement…</p>;
  return (
    <div className="space-y-3 text-sm text-slate-700" data-testid="vip-controle-section">
      <p>
        La ligne <b>{etat.ligne_vip || "Liluvine VIP"}</b> est réservée aux clients dont le <b>contrat est valide</b> (puce verte
        du Centre de messagerie). Un client dont le contrat est en retard (orange) ou absent (rouge) n'y a plus accès.
        {!etat.ligne_vip && <span className="text-amber-700"> Aucune ligne n'est encore marquée « VIP » dans les numéros WhatsApp.</span>}
      </p>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={actif} onChange={(e) => setActif(e.target.checked)} data-testid="vip-controle-actif" />
        <span>Activer le contrôle du contrat sur la ligne VIP</span>
      </label>
      <label className="block text-xs font-medium text-slate-700">
        Message envoyé au client qui écrit sur la ligne VIP sans contrat valide (une fois toutes les {etat.intervalle_heures} h au plus)
        <textarea rows={3} maxLength={1000} value={message} onChange={(e) => setMessage(e.target.value)} placeholder={etat.message_defaut}
          className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" data-testid="vip-controle-message" />
      </label>
      <label className="block text-xs font-medium text-slate-700">
        Notification à l'agent quand sa réponse est forcée sur la ligne standard
        <textarea rows={2} maxLength={500} value={notification} onChange={(e) => setNotification(e.target.value)} placeholder={etat.notification_defaut}
          className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" data-testid="vip-controle-notification" />
      </label>
      <p className="text-xs text-slate-500">
        Dans une conversation, l'agent choisit le canal (ligne) avant d'écrire. S'il choisit la ligne VIP pour un client sans contrat
        valide, le message part de la ligne standard et la notification ci-dessus s'affiche. Limite de WhatsApp : un texte libre n'est
        accepté que dans la fenêtre de 24 h ouverte avec le numéro que le client a écrit.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={enregistrer} disabled={occupe} data-testid="vip-controle-enregistrer"
          className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50">
          {occupe ? "Enregistrement…" : "Enregistrer"}
        </button>
        <Link to="/admin/messaging" className="text-xs text-sky-700 underline">Ouvrir le Centre de messagerie</Link>
      </div>
    </div>
  );
}
