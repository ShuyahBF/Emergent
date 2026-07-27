/* Iter43-fix24az-d (2026-02-26) — Quick contact-group toggler used at the
 * bottom of WhatsApp/SMS single-message dialogs.
 *
 * - Renders ALL contact-groups visible to the current tenant.
 * - Groups the contact already belongs to are styled in red ("appartient").
 * - Other groups are styled in black ("ne fait pas partie").
 * - Roles `admin`, `superviseur`, `moderateur` can click chips to
 *   add/remove the contact in one click (debounced via in-flight Set).
 * - Other roles see the chips read-only (display-only, click does nothing).
 *
 * The component is wrapped in a thick red border to be visually conspicuous
 * (as requested by the product owner).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Tags, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const TOGGLE_ROLES = new Set(["admin", "superviseur", "moderateur"]);

export const ContactGroupChips = ({ contact, userRole, onCountChange }) => {
  const [groups, setGroups] = useState([]);
  const [memberships, setMemberships] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(() => new Set());

  const canToggle = useMemo(
    () => TOGGLE_ROLES.has(String(userRole || "").toLowerCase()),
    [userRole]
  );

  // Iter43-fix24az-y (2026-07-22) — Notify parent of group-count changes so
  // the parent (ConversationModal) can display "Groupes (n)" in the tab title.
  useEffect(() => {
    if (typeof onCountChange === "function") {
      onCountChange(memberships.size);
    }
  }, [memberships, onCountChange]);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    apiClient
      .get("/me/contact-groups")
      .then((r) => {
        if (!mounted) return;
        const list = Array.isArray(r.data) ? r.data : [];
        setGroups(list);
        const inG = new Set();
        list.forEach((g) => {
          if ((g.contact_ids || []).includes(contact?.id)) inG.add(g.id);
        });
        setMemberships(inG);
      })
      .catch(() => {})
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [contact?.id]);

  const toggle = useCallback(async (g) => {
    if (!canToggle || !contact?.id) return;
    if (pending.has(g.id)) return;
    const wasMember = memberships.has(g.id);
    const next = new Set(pending);
    next.add(g.id);
    setPending(next);
    // Optimistic update
    const optimistic = new Set(memberships);
    if (wasMember) optimistic.delete(g.id);
    else optimistic.add(g.id);
    setMemberships(optimistic);
    try {
      if (wasMember) {
        await apiClient.delete(`/me/contact-groups/${g.id}/contacts/${contact.id}`);
        toast.success(`${contact.name || "Contact"} retiré du groupe « ${g.name} »`);
      } else {
        await apiClient.post(`/me/contact-groups/${g.id}/contacts`, { contact_ids: [contact.id] });
        toast.success(`${contact.name || "Contact"} ajouté au groupe « ${g.name} »`);
      }
    } catch (e) {
      // Revert optimistic state
      setMemberships(memberships);
      toast.error(e?.response?.data?.detail || "Échec de la mise à jour");
    } finally {
      setPending((prev) => {
        const n = new Set(prev);
        n.delete(g.id);
        return n;
      });
    }
  }, [canToggle, contact?.id, contact?.name, memberships, pending]);

  return (
    <div
      className="rounded-lg ring-2 ring-rose-500 bg-rose-50/30 px-3 py-2 mt-2"
      data-testid="contact-group-chips"
    >
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-rose-700 mb-1.5">
        <Tags className="h-3 w-3" />
        Groupes de contact
        {!canToggle && (
          <span className="ml-1 text-[10px] font-normal italic text-slate-500 normal-case">
            (lecture seule — admin/superviseur/modérateur uniquement)
          </span>
        )}
      </div>
      {loading ? (
        <p className="text-[11px] text-slate-500 inline-flex items-center gap-1">
          <Loader2 className="h-3 w-3 animate-spin" /> Chargement…
        </p>
      ) : groups.length === 0 ? (
        <p className="text-[11px] text-slate-500 italic">
          Aucun groupe créé. Allez dans <code>Mes contacts → Gérer les groupes</code> pour en créer.
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {groups.map((g) => {
            const isIn = memberships.has(g.id);
            const isPending = pending.has(g.id);
            return (
              <button
                key={g.id}
                type="button"
                onClick={() => toggle(g)}
                disabled={!canToggle || isPending}
                className={`text-[11px] px-2.5 py-1 rounded-full ring-1 transition inline-flex items-center gap-1 ${
                  isIn
                    ? "bg-rose-100 ring-rose-400 text-rose-800 font-semibold hover:bg-rose-200"
                    : "bg-white ring-slate-300 text-slate-800 hover:bg-slate-50"
                } ${!canToggle ? "cursor-default opacity-90" : "cursor-pointer"} ${isPending ? "opacity-60" : ""}`}
                title={
                  !canToggle
                    ? "Vous n'avez pas le droit de modifier l'appartenance"
                    : isIn ? `Cliquer pour retirer de « ${g.name} »`
                           : `Cliquer pour ajouter à « ${g.name} »`
                }
                data-testid={`contact-group-chip-${g.id}${isIn ? "-in" : "-out"}`}
              >
                {isPending && <Loader2 className="h-3 w-3 animate-spin" />}
                <span>{g.name}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default ContactGroupChips;
