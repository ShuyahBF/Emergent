/*
 * Iter43-fix24az-m (2026-07-18) — Planning médecins / RDV patients
 *
 * Vue :
 *   - Calendrier du jour (grille horaire 08h → 20h) avec RDVs par médecin
 *   - Sélecteur médecin (désactivé pour role='Médecin', qui voit son propre planning)
 *   - Sélecteur de date
 *   - Ligne rouge horizontale animée sur l'heure UTC courante
 *   - Sous le calendrier : liste des RDV du jour, les passés grisés et remontés
 *   - Auto-refresh toutes les 15s (temps réel)
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Calendar as CalendarIcon,
  Clock,
  User,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Stethoscope,
  Lock,
  Wifi,
  WifiOff,
} from "lucide-react";

// Configuration de la grille horaire (heures affichées, en UTC)
const START_HOUR = 8;
const END_HOUR = 20;
const SLOT_MINUTES = 30;
const PIXELS_PER_MINUTE = 1.5; // 1.5px/min → 90px/heure → grille lisible
const TOTAL_HEIGHT = (END_HOUR - START_HOUR) * 60 * PIXELS_PER_MINUTE;

function formatTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
  } catch {
    return "—";
  }
}

function todayISO() {
  const d = new Date();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

function addDays(iso, delta) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + delta);
  return `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, "0")}-${String(dt.getUTCDate()).padStart(2, "0")}`;
}

function minutesFromDayStart(iso) {
  // Renvoie les minutes depuis 00:00 UTC pour l'ISO donné
  try {
    const d = new Date(iso);
    return d.getUTCHours() * 60 + d.getUTCMinutes();
  } catch {
    return 0;
  }
}

function colorFromString(str) {
  const palette = [
    ["bg-violet-100", "border-violet-400", "text-violet-800"],
    ["bg-sky-100", "border-sky-400", "text-sky-800"],
    ["bg-emerald-100", "border-emerald-400", "text-emerald-800"],
    ["bg-amber-100", "border-amber-400", "text-amber-800"],
    ["bg-rose-100", "border-rose-400", "text-rose-800"],
    ["bg-indigo-100", "border-indigo-400", "text-indigo-800"],
    ["bg-teal-100", "border-teal-400", "text-teal-800"],
  ];
  let hash = 0;
  for (let i = 0; i < (str || "").length; i += 1) hash = (hash * 31 + str.charCodeAt(i)) & 0xffffffff;
  return palette[Math.abs(hash) % palette.length];
}

export default function Planning() {
  const [me, setMe] = useState(null);
  const [selectedDate, setSelectedDate] = useState(todayISO());
  const [doctors, setDoctors] = useState([]);
  const [selectedMedecinId, setSelectedMedecinId] = useState("");
  const [appointments, setAppointments] = useState([]);
  const [isMedecinView, setIsMedecinView] = useState(false);
  const [loading, setLoading] = useState(false);
  const [nowUtc, setNowUtc] = useState(new Date());
  const [sseConnected, setSseConnected] = useState(false);

  const isMedecin = (me?.tracked_role || "") === "Médecin";

  // -------- fetch --------
  const fetchMe = useCallback(async () => {
    try {
      const r = await apiClient.get("/auth/me");
      setMe(r.data);
    } catch (e) {
      toast.error("Impossible de récupérer votre profil");
    }
  }, []);

  const fetchDoctors = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/planning/doctors");
      const list = r.data?.doctors || [];
      setDoctors(list);
      // Si l'utilisateur est un médecin, force son propre id
      if (isMedecin && me?.id) {
        setSelectedMedecinId(me.id);
      }
    } catch (e) {
      /* silencieux — les endpoints existent mais pas de médecins encore */
    }
  }, [isMedecin, me?.id]);

  const fetchAppointments = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ date: selectedDate });
      if (selectedMedecinId) params.append("medecin_id", selectedMedecinId);
      const r = await apiClient.get(`/me/planning/appointments?${params.toString()}`);
      setAppointments(r.data?.items || []);
      setIsMedecinView(!!r.data?.is_medecin_view);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement des RDVs");
    } finally {
      setLoading(false);
    }
  }, [selectedDate, selectedMedecinId]);

  useEffect(() => { fetchMe(); }, [fetchMe]);
  useEffect(() => { if (me) fetchDoctors(); }, [me, fetchDoctors]);
  useEffect(() => { fetchAppointments(); }, [fetchAppointments]);

  // Iter43-fix24az-n — SSE stream temps réel (remplace le polling 15s)
  // Se connecte à /api/me/planning/stream avec le JWT en query param.
  // Fallback : si l'EventSource se déconnecte 3× de suite, on repasse au
  // polling 30s pour tenir même si CF ferme le stream.
  useEffect(() => {
    if (!me) return;
    const token = localStorage.getItem("sawali_token");
    if (!token) return;
    const params = new URLSearchParams({ token });
    if (selectedMedecinId) params.append("medecin_id", selectedMedecinId);
    const baseUrl = process.env.REACT_APP_BACKEND_URL || "";
    const url = `${baseUrl}/api/me/planning/stream?${params.toString()}`;

    let es;
    let reconnectAttempts = 0;
    let fallbackTimer;

    const upsertAppointment = (a) => {
      if (!a || !a.id) return;
      // Filtre côté client sur la date sélectionnée
      const aDate = (a.start_at || "").slice(0, 10);
      if (aDate !== selectedDate) return;
      setAppointments((prev) => {
        const idx = prev.findIndex((x) => x.id === a.id);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = { ...next[idx], ...a };
          return next;
        }
        return [...prev, a].sort((x, y) => (x.start_at || "").localeCompare(y.start_at || ""));
      });
    };

    const openStream = () => {
      try {
        es = new EventSource(url);
        es.addEventListener("hello", () => {
          reconnectAttempts = 0; // reset backoff
          setSseConnected(true);
        });
        es.addEventListener("ping", () => { /* keep-alive */ });
        es.addEventListener("created", (ev) => {
          try {
            const payload = JSON.parse(ev.data);
            upsertAppointment(payload.appointment);
            const p = payload.appointment;
            if (p && p.patient) toast.success(`Nouveau RDV : ${p.patient}`);
          } catch (err) { /* noop */ }
        });
        es.addEventListener("updated", (ev) => {
          try {
            const payload = JSON.parse(ev.data);
            upsertAppointment(payload.appointment);
          } catch (err) { /* noop */ }
        });
        es.onerror = () => {
          setSseConnected(false);
          es.close();
          reconnectAttempts += 1;
          if (reconnectAttempts <= 3) {
            // Exponential backoff : 2s, 4s, 8s
            const delay = Math.min(2000 * 2 ** (reconnectAttempts - 1), 30000);
            setTimeout(openStream, delay);
          } else {
            // Fallback : polling 30s après 3 échecs
            fallbackTimer = setInterval(() => {
              fetchAppointments();
            }, 30000);
          }
        };
      } catch (err) {
        setSseConnected(false);
      }
    };

    openStream();
    return () => {
      if (es) es.close();
      if (fallbackTimer) clearInterval(fallbackTimer);
    };
  }, [me, selectedMedecinId, selectedDate, fetchAppointments]);

  // Update UTC time every second (pour la ligne rouge)
  useEffect(() => {
    const t = setInterval(() => setNowUtc(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  // -------- computed --------
  const isToday = selectedDate === todayISO();
  const nowMinutes = nowUtc.getUTCHours() * 60 + nowUtc.getUTCMinutes();
  const dayStartMinutes = START_HOUR * 60;
  const redLineTop = isToday && nowMinutes >= dayStartMinutes && nowMinutes <= END_HOUR * 60
    ? (nowMinutes - dayStartMinutes) * PIXELS_PER_MINUTE
    : null;

  // Positionnement des RDVs sur la grille
  const positioned = useMemo(() => {
    return (appointments || []).map((a) => {
      const startMin = minutesFromDayStart(a.start_at);
      const endMin = minutesFromDayStart(a.end_at);
      const top = Math.max(0, (startMin - dayStartMinutes) * PIXELS_PER_MINUTE);
      const height = Math.max(20, (endMin - startMin) * PIXELS_PER_MINUTE - 2);
      const isPast = new Date(a.end_at).getTime() < nowUtc.getTime();
      return { ...a, top, height, isPast, startMin, endMin };
    });
  }, [appointments, dayStartMinutes, nowUtc]);

  // Tri liste : passés en premier (grisés), puis à venir triés par start_at
  const sortedList = useMemo(() => {
    const past = positioned.filter((a) => a.isPast).sort((x, y) => y.startMin - x.startMin);
    const upcoming = positioned.filter((a) => !a.isPast).sort((x, y) => x.startMin - y.startMin);
    return [...past, ...upcoming];
  }, [positioned]);

  // Slots verticaux
  const slots = useMemo(() => {
    const out = [];
    for (let h = START_HOUR; h < END_HOUR; h += 1) {
      for (let m = 0; m < 60; m += SLOT_MINUTES) {
        out.push({ h, m, top: ((h - START_HOUR) * 60 + m) * PIXELS_PER_MINUTE });
      }
    }
    return out;
  }, []);

  // -------- render --------
  return (
    <div className="max-w-6xl mx-auto p-4 space-y-4" data-testid="planning-root">
      {/* Header */}
      <div className="rounded-2xl bg-gradient-to-br from-sky-50 via-white to-violet-50 border border-slate-200 p-5 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-white border border-slate-200 flex items-center justify-center shadow-sm">
            <CalendarIcon className="h-5 w-5 text-sky-600" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-slate-800">Planning des consultations</h1>
            <p className="text-xs text-slate-500">Rendez-vous patients — mise à jour en temps réel</p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setSelectedDate((d) => addDays(d, -1))}
            className="p-2 rounded-lg hover:bg-slate-100 text-slate-700"
            data-testid="planning-prev-day"
            title="Jour précédent"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="px-2 py-1.5 border border-slate-300 rounded-lg text-sm bg-white"
            data-testid="planning-date-input"
          />
          <button
            onClick={() => setSelectedDate((d) => addDays(d, 1))}
            className="p-2 rounded-lg hover:bg-slate-100 text-slate-700"
            data-testid="planning-next-day"
            title="Jour suivant"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
          <button
            onClick={() => setSelectedDate(todayISO())}
            className="px-3 py-1.5 rounded-lg bg-white border border-slate-300 text-sm text-slate-700 hover:bg-slate-50"
            data-testid="planning-today-btn"
          >
            Aujourd'hui
          </button>
          <button
            onClick={fetchAppointments}
            className="p-2 rounded-lg hover:bg-slate-100 text-slate-600"
            disabled={loading}
            data-testid="planning-refresh"
            title="Rafraîchir"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
          <span
            className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-md border ${
              sseConnected
                ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                : "bg-slate-50 text-slate-500 border-slate-200"
            }`}
            data-testid="planning-sse-status"
            title={sseConnected ? "Push serveur actif — synchronisation temps réel" : "Push serveur inactif — appuyez sur Rafraîchir"}
          >
            {sseConnected ? <Wifi className="h-2.5 w-2.5" /> : <WifiOff className="h-2.5 w-2.5" />}
            {sseConnected ? "Live" : "Off"}
          </span>
        </div>
      </div>

      {/* Doctor filter */}
      <div className="bg-white border border-slate-200 rounded-xl p-3 flex items-center gap-3">
        <Stethoscope className="h-4 w-4 text-slate-500" />
        <span className="text-sm text-slate-600 shrink-0">Médecin :</span>
        <select
          value={selectedMedecinId}
          onChange={(e) => setSelectedMedecinId(e.target.value)}
          disabled={isMedecin}
          className="flex-1 px-3 py-1.5 rounded-lg border border-slate-300 text-sm disabled:bg-slate-100 disabled:text-slate-400 disabled:cursor-not-allowed"
          data-testid="planning-doctor-filter"
        >
          <option value="">— Tous les médecins —</option>
          {doctors.map((d) => (
            <option
              key={d.id}
              value={d.id}
              disabled={isMedecin && d.id !== me?.id}
            >
              {d.full_name || d.email}
              {isMedecin && d.id !== me?.id ? "  (verrouillé)" : ""}
            </option>
          ))}
        </select>
        {isMedecin && (
          <span className="inline-flex items-center gap-1 text-xs bg-amber-50 text-amber-700 px-2 py-1 rounded-md border border-amber-200" data-testid="planning-medecin-lock-badge">
            <Lock className="h-3 w-3" /> Consultation de votre planning
          </span>
        )}
      </div>

      {/* Calendar grid */}
      <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="grid grid-cols-[64px_1fr] relative" data-testid="planning-calendar-grid" style={{ height: TOTAL_HEIGHT + 20 }}>
          {/* Time column */}
          <div className="border-r border-slate-200 bg-slate-50">
            {slots.map((s, i) => (
              s.m === 0 ? (
                <div
                  key={i}
                  className="text-[11px] text-slate-500 pt-1 pr-2 text-right"
                  style={{ position: "absolute", top: s.top, right: "calc(100% - 64px)", width: 60 }}
                >
                  {String(s.h).padStart(2, "0")}:00
                </div>
              ) : null
            ))}
          </div>
          {/* Events column */}
          <div className="relative">
            {/* Slot lines */}
            {slots.map((s, i) => (
              <div
                key={i}
                className={`absolute left-0 right-0 border-t ${s.m === 0 ? "border-slate-200" : "border-slate-100"}`}
                style={{ top: s.top }}
              />
            ))}
            {/* Now indicator (red line) */}
            {redLineTop !== null && (
              <div
                className="absolute left-0 right-0 z-20 flex items-center pointer-events-none"
                style={{ top: redLineTop }}
                data-testid="planning-now-indicator"
              >
                <div className="w-2 h-2 rounded-full bg-red-600 -translate-x-1/2 shadow-md" />
                <div className="h-[2px] flex-1 bg-red-600 shadow-[0_0_6px_rgba(220,38,38,0.6)]" />
              </div>
            )}
            {/* Appointments */}
            {positioned.map((a) => {
              const [bg, border, textColor] = colorFromString(a.medecin || "");
              return (
                <div
                  key={a.id}
                  className={`absolute left-1 right-1 rounded-lg border-l-4 ${border} ${a.isPast ? "opacity-40 grayscale" : ""} shadow-sm ${bg} ${textColor} px-2 py-1 z-10 hover:shadow-md hover:z-30 transition-all cursor-default overflow-hidden`}
                  style={{ top: a.top, height: a.height }}
                  data-testid={`planning-event-${a.id}`}
                  title={`${a.medecin} — ${a.patient} (${formatTime(a.start_at)}–${formatTime(a.end_at)})`}
                >
                  <div className="text-[11px] font-semibold truncate leading-tight">
                    {formatTime(a.start_at)}–{formatTime(a.end_at)} · {a.patient}
                  </div>
                  <div className="text-[10px] opacity-80 truncate leading-tight">
                    {a.medecin}
                  </div>
                  {a.motif && (
                    <div className="text-[10px] italic opacity-70 truncate leading-tight">{a.motif}</div>
                  )}
                </div>
              );
            })}
            {/* Empty state */}
            {!loading && appointments.length === 0 && (
              <div className="absolute inset-0 flex items-center justify-center text-sm text-slate-400 pointer-events-none">
                Aucun rendez-vous pour cette journée
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Liste RDV sous le calendrier */}
      <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden" data-testid="planning-list">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <Clock className="h-4 w-4" /> Liste des rendez-vous ({sortedList.length})
          </h3>
          <div className="text-xs text-slate-400" data-testid="planning-now-utc">
            UTC {String(nowUtc.getUTCHours()).padStart(2, "0")}:{String(nowUtc.getUTCMinutes()).padStart(2, "0")}:{String(nowUtc.getUTCSeconds()).padStart(2, "0")}
          </div>
        </div>
        {sortedList.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-400">Aucun rendez-vous</div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {sortedList.map((a) => {
              const [bg, border, textColor] = colorFromString(a.medecin || "");
              return (
                <li
                  key={a.id}
                  className={`px-4 py-2.5 hover:bg-slate-50 transition-colors ${a.isPast ? "opacity-50" : ""}`}
                  data-testid={`planning-list-item-${a.id}`}
                >
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold border ${bg} ${border} ${textColor} shrink-0`}>
                        {formatTime(a.start_at)}–{formatTime(a.end_at)}
                      </span>
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-slate-800 truncate flex items-center gap-1.5">
                          <User className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                          {a.patient}
                          {a.isPast && (
                            <span className="text-[10px] uppercase tracking-wide text-slate-400 border border-slate-200 rounded px-1 py-0.5 ml-1">
                              Terminé
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-slate-500 truncate">
                          {a.medecin}
                          {a.motif ? ` · ${a.motif}` : ""}
                          {a.code_clinique ? ` · ${a.code_clinique}` : ""}
                        </div>
                      </div>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
