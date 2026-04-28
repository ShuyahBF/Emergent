import React from "react";
import * as LucideIcons from "lucide-react";

// Curated set of icons useful for both document categories and client categories.
export const ICON_NAMES = [
  "FileText", "BookOpen", "Megaphone", "FolderOpen", "ClipboardList", "Newspaper",
  "Cross", "Pill", "Stethoscope", "HeartPulse", "Microscope",
  "Store", "ShoppingBag", "ShoppingCart", "Receipt",
  "UtensilsCrossed", "Coffee", "Wheat",
  "Factory", "Wrench", "Hammer", "HardHat",
  "GraduationCap", "School", "Book",
  "Briefcase", "Building2", "Building", "Home",
  "Globe", "MapPin", "Truck", "Car",
  "Cpu", "Server", "Database", "Cloud",
  "Star", "Award", "Tag", "BadgeCheck",
];

export const COLOR_PALETTE = [
  "#1E90FF", "#0EA5E9", "#10B981", "#F59E0B",
  "#EF4444", "#8B5CF6", "#EC4899", "#6B7280",
  "#94A3B8", "#000000",
];

export function CategoryIcon({ name, color, className = "h-4 w-4", strokeWidth = 2 }) {
  const Cmp = (name && LucideIcons[name]) || LucideIcons.Tag;
  return <Cmp className={className} color={color || undefined} strokeWidth={strokeWidth} />;
}

export default function IconPicker({ value, color, onChange, onColorChange }) {
  return (
    <div className="space-y-2">
      <div>
        <label className="block text-xs font-semibold text-slate-700 mb-1">Icône</label>
        <div className="grid grid-cols-8 gap-1.5 max-h-40 overflow-auto p-2 border border-slate-200 rounded-lg bg-slate-50">
          {ICON_NAMES.map((n) => {
            const Cmp = LucideIcons[n] || LucideIcons.Tag;
            const active = value === n;
            return (
              <button
                key={n}
                type="button"
                onClick={() => onChange(n)}
                title={n}
                className={`p-2 rounded-md border transition ${active ? "border-sawali-blue bg-white shadow-sm" : "border-transparent bg-white hover:border-slate-300"}`}
                data-testid={`icon-pick-${n}`}
              >
                <Cmp className="h-4 w-4" color={active ? (color || "#1E90FF") : "#475569"} />
              </button>
            );
          })}
        </div>
      </div>
      <div>
        <label className="block text-xs font-semibold text-slate-700 mb-1">Couleur</label>
        <div className="flex flex-wrap gap-1.5">
          {COLOR_PALETTE.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => onColorChange(c)}
              className={`h-7 w-7 rounded-md border-2 ${color === c ? "border-slate-900 ring-2 ring-offset-1 ring-slate-300" : "border-white shadow-sm"}`}
              style={{ background: c }}
              title={c}
              data-testid={`color-pick-${c}`}
            />
          ))}
          <input
            type="color"
            value={color || "#1E90FF"}
            onChange={(e) => onColorChange(e.target.value)}
            className="h-7 w-7 rounded-md border border-slate-200 cursor-pointer"
            title="Choisir une couleur personnalisée"
          />
        </div>
      </div>
    </div>
  );
}
