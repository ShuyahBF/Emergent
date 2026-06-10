// Iter43 (2026-02) — Composant réutilisable pour activer le partage tenant
// sur les documents (rapports, suivis, notes, tâches, PV, groupes contacts).
//
// Utilisation :
//   <TenantSharingToggle
//     shared={form.shared_with_tenant}
//     editable={form.editable_by_tenant}
//     onChange={(next) => setForm({ ...form, ...next })}
//   />
//
// Affiche 2 checkboxes :
//   • Partager avec ma société     → expose le document aux collègues
//                                     (même `société` et/ou `rattachement`
//                                     selon le mode AND/OR du tenant)
//   • Autoriser l'édition collaborative → permet aux collègues de modifier
//                                          (option supplémentaire — décochée
//                                          par défaut)
import React from "react";
import { Users, Edit3 } from "lucide-react";

export default function TenantSharingToggle({
  shared = false,
  editable = false,
  onChange,
  compact = false,
  testidPrefix = "tenant-sharing",
}) {
  const set = (next) => onChange?.(next);
  return (
    <div className={`rounded-lg ring-1 ring-indigo-200 bg-indigo-50/50 ${compact ? "p-2" : "p-3"} space-y-1.5`} data-testid={`${testidPrefix}-block`}>
      <label className="flex items-start gap-2 cursor-pointer">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 accent-indigo-600"
          checked={!!shared}
          onChange={(e) => {
            const v = e.target.checked;
            set({ shared_with_tenant: v, editable_by_tenant: v ? editable : false });
          }}
          data-testid={`${testidPrefix}-shared`}
        />
        <span className="text-xs">
          <span className="font-medium text-indigo-900 inline-flex items-center gap-1">
            <Users className="h-3 w-3" /> Partager avec ma société
          </span>
          <span className="block text-[10px] text-indigo-700/80 mt-0.5">
            Les comptes ayant la même <strong>société</strong> et/ou <strong>rattachement</strong> verront ce document.
          </span>
        </span>
      </label>
      {shared && (
        <label className="flex items-start gap-2 cursor-pointer pl-6">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 accent-indigo-600"
            checked={!!editable}
            onChange={(e) => set({ shared_with_tenant: true, editable_by_tenant: e.target.checked })}
            data-testid={`${testidPrefix}-editable`}
          />
          <span className="text-xs">
            <span className="font-medium text-indigo-900 inline-flex items-center gap-1">
              <Edit3 className="h-3 w-3" /> Autoriser l&apos;édition collaborative
            </span>
            <span className="block text-[10px] text-indigo-700/80 mt-0.5">
              Si désactivé : lecture seule pour vos collègues. La suppression reste réservée à vous.
            </span>
          </span>
        </label>
      )}
    </div>
  );
}
