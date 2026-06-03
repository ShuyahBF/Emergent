// S-iter39p — Social share buttons displayed ONLY on videos and images
// of the « Brochures & Guides » portal page. Each platform opens its
// share intent in a new tab. We also expose a "Copy link" fallback.
import React, { useState } from "react";
import { toast } from "sonner";
import {
  Share2, Facebook, MessageCircle, Linkedin, Send, Mail,
  Link as LinkIcon, Twitter, Youtube, Music,
} from "lucide-react";

const PLATFORMS = [
  {
    key: "whatsapp",
    label: "WhatsApp",
    icon: MessageCircle,
    color: "bg-emerald-500 hover:bg-emerald-600",
    href: ({ url, text }) => `https://wa.me/?text=${encodeURIComponent(text + " " + url)}`,
  },
  {
    key: "facebook",
    label: "Facebook",
    icon: Facebook,
    color: "bg-[#1877F2] hover:bg-[#0e6ad6]",
    href: ({ url }) => `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}`,
  },
  {
    key: "twitter",
    label: "X / Twitter",
    icon: Twitter,
    color: "bg-slate-900 hover:bg-black",
    href: ({ url, text }) => `https://twitter.com/intent/tweet?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`,
  },
  {
    key: "linkedin",
    label: "LinkedIn",
    icon: Linkedin,
    color: "bg-[#0A66C2] hover:bg-[#085ba9]",
    href: ({ url }) => `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`,
  },
  {
    key: "telegram",
    label: "Telegram",
    icon: Send,
    color: "bg-[#26A5E4] hover:bg-[#1e95cf]",
    href: ({ url, text }) => `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`,
  },
  {
    key: "email",
    label: "Email",
    icon: Mail,
    color: "bg-slate-500 hover:bg-slate-600",
    href: ({ url, text }) => `mailto:?subject=${encodeURIComponent(text)}&body=${encodeURIComponent(url)}`,
  },
  {
    key: "youtube",
    label: "YouTube",
    icon: Youtube,
    color: "bg-[#FF0000] hover:bg-[#cc0000]",
    href: () => "https://studio.youtube.com/channel/UC/videos/upload",
    note: "YouTube exige un téléversement depuis l'interface — un onglet vers YouTube Studio s'ouvre.",
  },
  {
    key: "tiktok",
    label: "TikTok",
    icon: Music,
    color: "bg-black hover:bg-slate-800",
    href: () => "https://www.tiktok.com/upload",
    note: "TikTok exige un téléversement manuel — un onglet vers TikTok Upload s'ouvre.",
  },
];

export default function SocialShareButtons({ url, title, kind, compact = false }) {
  const [open, setOpen] = useState(false);
  if (!url) return null;
  const fullUrl = url.startsWith("http") ? url : `${window.location.origin}${url}`;
  const text = title || "Contenu SAWALI";

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(fullUrl);
      toast.success("Lien copié dans le presse-papier");
    } catch {
      toast.error("Impossible de copier — sélectionnez et copiez manuellement.");
    }
  };

  const onShare = (p) => {
    if (p.note) toast.info(p.note);
    const target = typeof p.href === "function" ? p.href({ url: fullUrl, text }) : p.href;
    window.open(target, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="relative inline-block" data-testid={`social-share-${kind}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full ring-1 ring-slate-300 hover:ring-slate-400 bg-white/90 backdrop-blur-sm text-slate-700 ${compact ? "" : ""}`}
        data-testid="social-share-trigger"
      >
        <Share2 className="h-3.5 w-3.5" />
        {compact ? "" : "Partager"}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 rounded-xl ring-1 ring-slate-200 bg-white shadow-xl p-2 min-w-[220px]" data-testid="social-share-menu">
            <p className="text-[10px] uppercase tracking-wider text-slate-400 px-2 pt-1 pb-2 font-semibold">Partager sur</p>
            <div className="grid grid-cols-2 gap-1">
              {PLATFORMS.map((p) => (
                <button
                  key={p.key}
                  onClick={() => onShare(p)}
                  className={`inline-flex items-center gap-1.5 text-[11px] px-2 py-1.5 rounded text-white ${p.color}`}
                  data-testid={`social-share-${p.key}`}
                >
                  <p.icon className="h-3.5 w-3.5" />
                  <span className="truncate">{p.label}</span>
                </button>
              ))}
            </div>
            <button
              onClick={copyLink}
              className="w-full mt-2 text-[11px] inline-flex items-center justify-center gap-1.5 px-2 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50"
              data-testid="social-share-copy"
            >
              <LinkIcon className="h-3.5 w-3.5" />
              Copier le lien
            </button>
          </div>
        </>
      )}
    </div>
  );
}
