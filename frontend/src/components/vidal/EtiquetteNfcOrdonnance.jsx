// components/vidal/EtiquetteNfcOrdonnance.jsx
// ------------------------------------------------
// Lot 383 (pharmacie, lot P1) — « Écrire sur une étiquette NFC » : le médecin écrit, depuis son téléphone Android (Chrome, page en HTTPS), le lien de la page de l'officine
// sur une étiquette NFC vierge à coller sur l'ordonnance papier. La pharmacie pose son téléphone dessus : la page de l'officine s'ouvre toute seule (aucune application).
//
// Chaque étape s'affiche à l'écran (comme le laboratoire NFC de Personnel de maison) :
//   1. compatibilité du navigateur (Web NFC : Chrome sur Android, HTTPS) ; 2. lien demandé à SAWALI (et place qu'il occupe sur l'étiquette) ;
//   3. attente de l'étiquette vierge ; 4. écriture ; 5. relecture et comparaison avec le lien écrit ; 6. étiquette notée dans le journal de l'ordonnance.
// Le lien ne contient qu'un jeton aléatoire : ni nom de patient, ni médicament. L'étiquette n'est jamais verrouillée (on peut la réécrire).
import { useRef, useState } from "react";
import { CheckCircle2, Copy, Info, Loader2, Radio, XCircle } from "lucide-react";
import { apiClient as api } from "@/lib/api";

import { X as Ico15X } from "lucide-react";
const ICONES = {
  ok: <CheckCircle2 size={14} style={{ color: "#166534" }} />,
  echec: <XCircle size={14} style={{ color: "#b91c1c" }} />,
  cours: <Loader2 size={14} className="animate-spin" style={{ color: "#b45309" }} />,
  info: <Info size={14} style={{ color: "#1d4ed8" }} />,
};

export default function EtiquetteNfcOrdonnance({ ordonnanceId, onFermer }) {
  const [etapes, setEtapes] = useState([]);       // journal : { texte, etat: ok | echec | cours | info, detail }
  const [actif, setActif] = useState(false);
  const [lien, setLien] = useState("");
  const [copie, setCopie] = useState(false);
  const arret = useRef(null);                       // AbortController de l'opération en cours

  // Ajoute une étape ; si `remplace`, la dernière étape « en cours » est remplacée par son résultat
  const noter = (texte, etat, detail = "", remplace = false) =>
    setEtapes((prec) => {
      const base = remplace && prec.length && prec[prec.length - 1].etat === "cours" ? prec.slice(0, -1) : prec;
      return [...base, { texte, etat, detail, heure: new Date().toLocaleTimeString("fr-FR") }];
    });

  const nfcDisponible = typeof window !== "undefined" && "NDEFReader" in window && window.isSecureContext;

  const demarrer = async () => {
    setEtapes([]); setActif(true); setCopie(false);
    arret.current = new AbortController();
    const signal = arret.current.signal;
    try {
      // 1. compatibilité
      if (!nfcDisponible) {
        noter("Compatibilité du navigateur", "echec", "Web NFC n'est disponible que sur Chrome pour Android, en HTTPS. Utilisez le téléphone du médecin, ou copiez le lien et écrivez-le avec une application NFC.");
        return;
      }
      noter("Compatibilité du navigateur", "ok", "Web NFC disponible");
      // 2. lien
      noter("Lien de l'ordonnance", "cours", "demande à SAWALI…");
      const r = await api.get(`/vidal/ordonnances/${ordonnanceId}/nfc`);
      const { url, octets, etiquettes } = r.data;
      setLien(url);
      const tient = Object.entries(etiquettes || {}).filter(([, v]) => v.tient).map(([nom]) => nom);
      noter("Lien de l'ordonnance", "ok", `${url} — ${octets} octets ; tient sur : ${tient.join(", ") || "aucune étiquette courante"}`, true);
      if (!tient.length) { noter("Arrêt", "echec", "Le lien est trop long pour les étiquettes courantes."); return; }
      // 3-4. attente puis écriture : Chrome écrit dès qu'une étiquette est approchée
      noter("En attente d'une étiquette NFC vierge", "cours", "approchez-la du dos du téléphone (30 secondes)…");
      const delai = setTimeout(() => arret.current?.abort(), 30000);
      const nfc = new window.NDEFReader();
      await nfc.write({ records: [{ recordType: "url", data: url }] }, { overwrite: true, signal });
      clearTimeout(delai);
      noter("Écriture", "ok", "le lien est écrit sur l'étiquette", true);
      // 5. relecture
      noter("Vérification : relecture", "cours", "reposez la MÊME étiquette contre le téléphone pour la relire…");
      const relu = await new Promise((resolve, reject) => {
        const lecteur = new window.NDEFReader();
        const minuteur = setTimeout(() => { arret.current?.abort(); reject(new Error("délai dépassé")); }, 30000);
        lecteur.addEventListener("reading", ({ message }) => {
          clearTimeout(minuteur);
          const rec = (message.records || []).find((x) => x.recordType === "url");
          resolve(rec ? new TextDecoder().decode(rec.data) : null);
        });
        lecteur.addEventListener("readingerror", () => { clearTimeout(minuteur); reject(new Error("lecture impossible")); });
        lecteur.scan({ signal }).catch(reject);
      });
      arret.current?.abort();
      if (relu === url) {
        noter("Vérification : relecture", "ok", "le lien relu est IDENTIQUE au lien écrit", true);
        // 6. journal
        await api.post(`/vidal/ordonnances/${ordonnanceId}/nfc-ecrite`).catch(() => {});
        noter("Étiquette prête", "ok", "collez-la sur l'ordonnance, près du QR. Elle n'est pas verrouillée : vous pouvez la réécrire.");
      } else {
        noter("Vérification : relecture", "echec", `le lien relu est DIFFÉRENT (${relu || "aucun lien"}) : recommencez avec une autre étiquette.`, true);
      }
    } catch (e) {
      const nom = e?.name || "";
      const texte = nom === "NotAllowedError" ? "Autorisation NFC refusée : acceptez la demande de Chrome." : nom === "NotSupportedError" ? "NFC désactivé ou non pris en charge : activez-le dans les réglages du téléphone."
        : nom === "AbortError" ? "Aucune étiquette détectée en 30 secondes (ou opération arrêtée)." : e?.response?.data?.detail || e?.message || "Échec de l'écriture. Gardez l'étiquette contre le téléphone et recommencez.";
      noter("Échec", "echec", texte, true);
    } finally {
      setActif(false);
    }
  };

  const arreter = () => { arret.current?.abort(); setActif(false); };
  const copier = async () => { try { await navigator.clipboard.writeText(lien); setCopie(true); } catch { /* presse-papiers indisponible */ } };

  return (
    <div style={{ marginTop: 8, padding: 10, border: "1px solid var(--vidal-bordure)", borderRadius: 10, background: "#f8fafc" }} data-testid="etiquette-nfc">
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: 13 }}>
        <Radio size={14} /> Étiquette NFC de l'ordonnance
        <button type="button" className="bouton-secondaire" style={{ marginLeft: "auto", fontSize: 11 }} onClick={() => { arreter(); onFermer(); }}><Ico15X className="inline-block h-4 w-4 shrink-0 mr-1" aria-hidden="true" />Fermer</button>
      </div>
      <div style={{ fontSize: 12, color: "var(--vidal-gris)", margin: "4px 0 8px" }}>
        Écrit le lien de la page de l'officine sur une étiquette NFC vierge (NTAG213 ou plus) à coller sur l'ordonnance. La pharmacie pose son téléphone dessus : la page s'ouvre toute seule.
        Le lien ne contient aucune donnée de santé.
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {actif
          ? <button type="button" className="bouton-secondaire" onClick={arreter}><XCircle size={13} /> Arrêter</button>
          : <button type="button" className="bouton" onClick={demarrer} data-testid="nfc-demarrer"><Radio size={13} /> {etapes.length ? "Recommencer" : "Écrire l'étiquette"}</button>}
        {lien && <button type="button" className="bouton-secondaire" onClick={copier}><Copy size={13} /> {copie ? "Lien copié" : "Copier le lien"}</button>}
      </div>
      {etapes.length > 0 && (
        <ul style={{ listStyle: "none", margin: "8px 0 0", padding: 0, display: "grid", gap: 4 }}>
          {etapes.map((e, i) => (
            <li key={i} style={{ display: "flex", gap: 6, alignItems: "flex-start", fontSize: 12.5 }}>
              <span style={{ marginTop: 2 }}>{ICONES[e.etat]}</span>
              <span><b>{e.texte}</b>{e.detail ? ` — ${e.detail}` : ""} <span style={{ color: "var(--vidal-gris)", fontSize: 10.5 }}>{e.heure}</span></span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
