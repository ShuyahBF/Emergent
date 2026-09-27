/*
  SurveySendModal — lot 27 : envoi d'un sondage WhatsApp à plusieurs destinataires.

  Étape 1 « Destinataires » (sauf relance) :
    - clients : TOUS les contacts d'un ou plusieurs comptes clients (ex. PHL) ;
    - groupes de contacts ; entreprise du contact ; contacts cherchés un à un ;
    - « exclure les contacts déjà invités » (coché par défaut) ;
    - échantillon aléatoire (ex. 100 contacts tirés au hasard) ;
    - la liste obtenue se vérifie et se décoche avant l'envoi.
  Étape 2 « Message » :
    - Auto (conseillé) : message libre pour les contacts qui ont écrit dans
      les 24 h, modèle Meta pour les autres ;
    - Modèle Meta seulement, ou Message libre seulement ;
    - {{lien}} (lien personnel) doit figurer dans le modèle ; pour un bouton
      lien dont l'adresse finit par une variable, mettre {{jeton}}.
  Relance (prop `reminder`) : renvoie le même lien aux invités qui n'ont pas
  encore répondu ; seule l'étape « Message » est affichée.
*/
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { X, Users, Search, Shuffle, Send, CheckSquare, Square, MessageCircle, Loader2 } from "lucide-react";
import { parseTemplate, buildButtonSpecs } from "@/lib/waTemplate";

export default function SurveySendModal({ survey, reminder = false, waitingCount = 0, onClose, onSent }) {
  const [step, setStep] = useState(reminder ? 2 : 1);
  // Sources de destinataires
  const [roster, setRoster] = useState([]);
  const [groups, setGroups] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [clientIds, setClientIds] = useState([]);
  const [groupIds, setGroupIds] = useState([]);
  const [contactIds, setContactIds] = useState([]);
  const [company, setCompany] = useState("");
  const [clientSearch, setClientSearch] = useState("");
  const [contactSearch, setContactSearch] = useState("");
  const [excludeInvited, setExcludeInvited] = useState(true);
  const [sampleSize, setSampleSize] = useState("");
  // Liste vérifiée
  const [preview, setPreview] = useState(null);
  const [checked, setChecked] = useState(new Set());
  const [loadingPreview, setLoadingPreview] = useState(false);
  // Message
  const [templates, setTemplates] = useState([]);
  const [mode, setMode] = useState("auto");
  const [templateName, setTemplateName] = useState("");
  const [bodyVars, setBodyVars] = useState([]);
  const [buttonVars, setButtonVars] = useState([]);
  const [textMessage, setTextMessage] = useState(survey.message_text || "");
  const [sending, setSending] = useState(false);

  // Chargement des listes (clients, groupes, contacts, modèles Meta)
  useEffect(() => {
    const safe = (p) => p.then((r) => r.data).catch(() => null);
    Promise.all([
      safe(apiClient.get("/me/clients-roster")), safe(apiClient.get("/me/contact-groups")),
      safe(apiClient.get("/me/contacts")), safe(apiClient.get("/me/whatsapp/templates")),
      survey.message_text ? Promise.resolve(null) : safe(apiClient.get(`/me/wa-surveys/${survey.id}`)),
    ]).then(([r, g, c, t, full]) => {
      setRoster(Array.isArray(r) ? r : r?.items || []);
      setGroups(Array.isArray(g) ? g : g?.items || []);
      setContacts(Array.isArray(c) ? c : c?.items || []);
      setTemplates(t?.items || []);
      if (full?.message_text) setTextMessage(full.message_text);
    });
  }, [survey.id, survey.message_text]);

  const template = useMemo(() => templates.find((t) => t.name === templateName) || null, [templates, templateName]);
  const parsed = useMemo(() => (template ? parseTemplate(template) : null), [template]);
  // Valeurs proposées : 1re variable = nom, dernière = lien ; bouton lien = jeton
  useEffect(() => {
    if (!parsed) { setBodyVars([]); setButtonVars([]); return; }
    const n = parsed.body.varCount || 0;
    setBodyVars(Array.from({ length: n }, (_, i) => (i === n - 1 ? "{{lien}}" : i === 0 ? "{{name}}" : "")));
    setButtonVars((parsed.buttons || []).map((b) => Array.from({ length: b.urlVarCount || 0 }, () => "{{jeton}}")));
  }, [parsed]);

  const filteredRoster = useMemo(() => {
    const q = clientSearch.trim().toLowerCase();
    return roster.filter((c) => !q || `${c.full_name || ""} ${c.company || ""} ${c.client_code || ""}`.toLowerCase().includes(q)).slice(0, 60);
  }, [roster, clientSearch]);
  const foundContacts = useMemo(() => {
    const q = contactSearch.trim().toLowerCase();
    if (q.length < 2) return [];
    return contacts.filter((c) => (c.whatsapp || c.phone) && `${c.name || ""} ${c.company || ""}`.toLowerCase().includes(q)).slice(0, 30);
  }, [contacts, contactSearch]);

  const toggle = (list, setList, id) => setList(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const hasSource = clientIds.length || groupIds.length || contactIds.length || company.trim();

  // Étape 1 -> liste des destinataires calculée par le serveur
  const loadPreview = async () => {
    setLoadingPreview(true);
    try {
      const r = await apiClient.post("/me/wa-surveys/recipients/preview", {
        client_ids: clientIds, group_ids: groupIds, contact_ids: contactIds, company: company.trim() || null,
        survey_id: survey.id, exclude_invited: excludeInvited, sample_size: parseInt(sampleSize, 10) || null,
      });
      setPreview(r.data);
      setChecked(new Set((r.data.items || []).map((i) => i.id)));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible de calculer les destinataires");
    } finally {
      setLoadingPreview(false);
    }
  };

  const selected = (preview?.items || []).filter((i) => checked.has(i.id));
  const windowOpenSelected = selected.filter((i) => i.window_open).length;
  const needsTemplate = mode === "template" || (mode === "auto" && !reminder && windowOpenSelected < selected.length) || (mode === "auto" && reminder);

  const send = async () => {
    if (!reminder && !selected.length) { toast.error("Aucun destinataire coché"); return; }
    if (mode === "template" && !templateName) { toast.error("Choisissez un modèle Meta"); return; }
    setSending(true);
    try {
      const r = await apiClient.post(`/me/wa-surveys/${survey.id}/send`, {
        contact_ids: reminder ? [] : selected.map((i) => i.id), reminder, mode,
        template_name: mode === "text" ? null : templateName || null,
        language_code: template?.language || "fr", variables: mode === "text" ? [] : bodyVars,
        button_specs: parsed && mode !== "text" ? buildButtonSpecs(parsed, buttonVars) : null,
        text_message: textMessage,
      });
      toast.success(`Envoi lancé vers ${r.data?.campaign?.total || 0} destinataire(s) — suivez la progression dans les résultats`);
      onSent?.(r.data?.campaign);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Envoi impossible");
    } finally {
      setSending(false);
    }
  };

  const chip = (active) => `text-xs px-2.5 py-1 rounded-full ring-1 transition ${active ? "bg-sawali-blue text-white ring-sawali-blue" : "bg-white ring-slate-200 hover:ring-sawali-blue/50"}`;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" data-testid="survey-send-modal"
      onClick={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className="w-full max-w-3xl max-h-[92vh] overflow-auto rounded-2xl bg-white shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-slate-200 bg-white px-5 py-3">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-wider text-slate-500">{reminder ? "Relance" : `Envoi — étape ${step} / 2`}</p>
            <h2 className="font-semibold text-slate-900 truncate">{survey.title}</h2>
          </div>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-slate-100" title="Fermer"><X className="h-5 w-5" /></button>
        </div>

        {step === 1 && (
          <div className="p-5 space-y-5">
            {/* Clients : tous leurs contacts */}
            <section>
              <p className="text-sm font-semibold text-slate-800 flex items-center gap-1.5"><Users className="h-4 w-4" /> Tous les contacts d'un client</p>
              <div className="relative mt-2 max-w-xs">
                <Search className="absolute left-2.5 top-2 h-4 w-4 text-slate-400" />
                <input value={clientSearch} onChange={(e) => setClientSearch(e.target.value)} placeholder="Chercher un client (ex. PHL)"
                  className="w-full rounded-lg border border-slate-300 pl-8 pr-2 py-1.5 text-sm" data-testid="send-client-search" />
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5 max-h-32 overflow-auto">
                {filteredRoster.map((c) => (
                  <button key={c.id} onClick={() => toggle(clientIds, setClientIds, c.id)} className={chip(clientIds.includes(c.id))}
                    data-testid={`send-client-${c.id}`}>
                    {c.company || c.full_name}{c.client_code ? ` · ${c.client_code}` : ""}
                  </button>
                ))}
                {!filteredRoster.length && <span className="text-xs text-slate-400">Aucun client</span>}
              </div>
            </section>
            {/* Groupes */}
            {groups.length > 0 && (
              <section>
                <p className="text-sm font-semibold text-slate-800">Groupes de contacts</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {groups.map((g) => (
                    <button key={g.id} onClick={() => toggle(groupIds, setGroupIds, g.id)} className={chip(groupIds.includes(g.id))}
                      style={groupIds.includes(g.id) && g.color ? { background: g.color } : {}}>
                      {g.name} ({(g.contact_ids || []).length})
                    </button>
                  ))}
                </div>
              </section>
            )}
            {/* Entreprise + contacts un à un */}
            <section className="grid sm:grid-cols-2 gap-4">
              <label className="text-sm font-semibold text-slate-800">Entreprise du contact (contient)
                <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="ex. Pharmacie"
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-normal" data-testid="send-company" />
              </label>
              <div>
                <p className="text-sm font-semibold text-slate-800">Ajouter des contacts</p>
                <input value={contactSearch} onChange={(e) => setContactSearch(e.target.value)} placeholder="Nom ou entreprise (2 lettres min.)"
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm" />
                <div className="mt-1 max-h-28 overflow-auto space-y-0.5">
                  {foundContacts.map((c) => (
                    <label key={c.id} className="flex items-center gap-2 text-xs text-slate-700 cursor-pointer">
                      <input type="checkbox" checked={contactIds.includes(c.id)} onChange={() => toggle(contactIds, setContactIds, c.id)} />
                      {c.name || c.company} <span className="text-slate-400">{c.company}</span>
                    </label>
                  ))}
                </div>
                {contactIds.length > 0 && <p className="text-[11px] text-sawali-blue mt-1">{contactIds.length} contact(s) ajouté(s)</p>}
              </div>
            </section>
            {/* Options d'échantillonnage */}
            <section className="flex flex-wrap items-center gap-4 rounded-lg bg-slate-50 p-3">
              <label className="inline-flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={excludeInvited} onChange={(e) => setExcludeInvited(e.target.checked)} />
                Exclure les contacts déjà invités à ce sondage
              </label>
              <label className="inline-flex items-center gap-2 text-sm text-slate-700">
                <Shuffle className="h-4 w-4 text-slate-500" /> Échantillon aléatoire de
                <input type="number" min={1} value={sampleSize} onChange={(e) => setSampleSize(e.target.value)} placeholder="tous"
                  className="w-20 rounded border border-slate-300 px-2 py-1 text-sm" data-testid="send-sample" /> contacts
              </label>
            </section>
            <button onClick={loadPreview} disabled={!hasSource || loadingPreview} data-testid="send-preview-btn"
              className="inline-flex items-center gap-2 rounded-lg bg-slate-900 text-white px-4 py-2 text-sm hover:bg-slate-800 disabled:opacity-40">
              {loadingPreview ? <Loader2 className="h-4 w-4 animate-spin" /> : <Users className="h-4 w-4" />} Voir les destinataires
            </button>

            {preview && (
              <section className="rounded-xl ring-1 ring-slate-200" data-testid="send-preview">
                <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 px-3 py-2 text-xs text-slate-600">
                  <span><b className="text-slate-900">{selected.length}</b> / {preview.items.length} coché(s)</span>
                  {preview.excluded_invited > 0 && <span>{preview.excluded_invited} déjà invité(s) exclu(s)</span>}
                  {preview.sampled && <span className="text-indigo-600">échantillon aléatoire parmi {preview.total_found - preview.excluded_invited}</span>}
                  <span className="text-emerald-700">{windowOpenSelected} joignable(s) par message libre</span>
                  <button onClick={() => setChecked(checked.size === preview.items.length ? new Set() : new Set(preview.items.map((i) => i.id)))}
                    className="ml-auto text-sawali-blue hover:underline">
                    {checked.size === preview.items.length ? "Tout décocher" : "Tout cocher"}
                  </button>
                </div>
                <div className="max-h-56 overflow-auto divide-y divide-slate-100">
                  {preview.items.map((i) => (
                    <label key={i.id} className="flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer hover:bg-slate-50">
                      <button type="button" onClick={() => { const n = new Set(checked); n.has(i.id) ? n.delete(i.id) : n.add(i.id); setChecked(n); }}>
                        {checked.has(i.id) ? <CheckSquare className="h-4 w-4 text-sawali-blue" /> : <Square className="h-4 w-4 text-slate-400" />}
                      </button>
                      <span className="flex-1 min-w-0 truncate">{i.name} <span className="text-xs text-slate-400">{i.company}</span></span>
                      <span className="text-[11px] text-slate-400 tabular-nums">{i.phone}</span>
                      {i.window_open && <span title="Vous a écrit dans les 24 h" className="text-[10px] rounded bg-emerald-100 text-emerald-700 px-1.5">24 h</span>}
                      {i.already_invited && <span className="text-[10px] rounded bg-amber-100 text-amber-700 px-1.5">{i.already_answered ? "a répondu" : "déjà invité"}</span>}
                    </label>
                  ))}
                  {!preview.items.length && <p className="px-3 py-4 text-sm text-slate-500">Aucun contact WhatsApp trouvé.</p>}
                </div>
              </section>
            )}
            <div className="flex justify-end">
              <button onClick={() => setStep(2)} disabled={!selected.length} data-testid="send-next"
                className="rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-40">
                Suivant : le message
              </button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="p-5 space-y-4">
            <p className="text-sm text-slate-600">
              {reminder
                ? <>Relance de <b>{waitingCount}</b> invité(s) qui n'ont pas encore répondu (même lien personnel).</>
                : <><b>{selected.length}</b> destinataire(s), dont <b>{windowOpenSelected}</b> joignable(s) par message libre (ils vous ont écrit dans les 24 h).</>}
            </p>
            <div className="flex flex-wrap gap-2">
              {[["auto", "Auto (conseillé)"], ["template", "Modèle Meta seulement"], ["text", "Message libre seulement"]].map(([k, l]) => (
                <button key={k} onClick={() => setMode(k)} className={chip(mode === k)} data-testid={`send-mode-${k}`}>{l}</button>
              ))}
            </div>
            <p className="text-[11px] text-slate-500">
              {mode === "auto" && "Message libre pour les contacts qui vous ont écrit dans les 24 h, modèle Meta pour les autres (règle de WhatsApp)."}
              {mode === "template" && "Tous les destinataires reçoivent le modèle Meta choisi."}
              {mode === "text" && "Seuls les contacts qui vous ont écrit dans les 24 h reçoivent le message ; les autres sont ignorés."}
            </p>

            {mode !== "text" && (
              <section className="rounded-xl ring-1 ring-slate-200 p-3 space-y-2">
                <label className="text-sm font-semibold text-slate-800">Modèle Meta {needsTemplate && <span className="text-rose-500">*</span>}
                  <select value={templateName} onChange={(e) => setTemplateName(e.target.value)} data-testid="send-template"
                    className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm font-normal">
                    <option value="">— Choisir un modèle approuvé —</option>
                    {templates.map((t) => <option key={`${t.name}-${t.language}`} value={t.name}>{t.name} · {t.language}</option>)}
                  </select>
                </label>
                {parsed && (
                  <>
                    <p className="rounded-lg bg-emerald-50 p-2 text-xs text-slate-700 whitespace-pre-line">{parsed.body.text}</p>
                    {bodyVars.map((v, i) => (
                      <label key={i} className="flex items-center gap-2 text-xs text-slate-600">
                        <span className="w-12 shrink-0 font-mono">{`{{${i + 1}}}`}</span>
                        <input value={v} onChange={(e) => setBodyVars(bodyVars.map((x, k) => (k === i ? e.target.value : x)))}
                          className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm" data-testid={`send-var-${i}`} />
                      </label>
                    ))}
                    {parsed.buttons.map((b, bi) => (b.urlVarCount > 0 ? (
                      <label key={bi} className="flex items-center gap-2 text-xs text-slate-600">
                        <span className="shrink-0">Bouton « {b.text} » — fin de l'adresse</span>
                        <input value={buttonVars[bi]?.[0] || ""} onChange={(e) => setButtonVars(buttonVars.map((x, k) => (k === bi ? [e.target.value] : x)))}
                          className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm" />
                      </label>
                    ) : null))}
                    <p className="text-[11px] text-slate-500">
                      <code>{"{{lien}}"}</code> = lien personnel du sondage (obligatoire dans une variable) · <code>{"{{name}}"}</code> = nom du contact ·
                      bouton dont l'adresse se termine par une variable (ex. …/s/{"{{1}}"}) : <code>{"{{jeton}}"}</code>.
                    </p>
                  </>
                )}
              </section>
            )}
            {mode !== "template" && (
              <section className="rounded-xl ring-1 ring-slate-200 p-3 space-y-1">
                <p className="text-sm font-semibold text-slate-800 flex items-center gap-1.5"><MessageCircle className="h-4 w-4" /> Message libre</p>
                <textarea value={textMessage} onChange={(e) => setTextMessage(e.target.value)} rows={3} maxLength={1000}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="send-text" />
                <p className="text-[11px] text-slate-500">Le lien est ajouté à la fin s'il n'y figure pas ({"{{lien}}"}).</p>
              </section>
            )}
            <div className="flex justify-between gap-2">
              {!reminder ? <button onClick={() => setStep(1)} className="text-sm text-slate-600 hover:underline">← Destinataires</button> : <span />}
              <button onClick={send} disabled={sending || (needsTemplate && mode !== "text" && !templateName && mode === "template")}
                data-testid="send-confirm"
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 text-white px-4 py-2 text-sm font-semibold hover:bg-emerald-700 disabled:opacity-40">
                {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {reminder ? "Relancer" : `Envoyer à ${selected.length}`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
