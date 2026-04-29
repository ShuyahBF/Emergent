import {
  FileText, FileImage, FileAudio, FileVideo, FileSpreadsheet, FileCode,
  FileArchive, FileType, File as FileGeneric, Presentation,
} from "lucide-react";

// Map of file extensions to a Lucide icon and a brand color.
// Used to render a recognizable thumbnail for each uploaded document.
const EXT_MAP = {
  // PDF
  pdf: { icon: FileType, color: "#DC2626" },
  // Word
  doc: { icon: FileText, color: "#1D4ED8" },
  docx: { icon: FileText, color: "#1D4ED8" },
  rtf: { icon: FileText, color: "#1D4ED8" },
  odt: { icon: FileText, color: "#1D4ED8" },
  // Excel
  xls: { icon: FileSpreadsheet, color: "#16A34A" },
  xlsx: { icon: FileSpreadsheet, color: "#16A34A" },
  csv: { icon: FileSpreadsheet, color: "#15803D" },
  ods: { icon: FileSpreadsheet, color: "#16A34A" },
  // PowerPoint
  ppt: { icon: Presentation, color: "#EA580C" },
  pptx: { icon: Presentation, color: "#EA580C" },
  odp: { icon: Presentation, color: "#EA580C" },
  // Image
  png: { icon: FileImage, color: "#7C3AED" },
  jpg: { icon: FileImage, color: "#7C3AED" },
  jpeg: { icon: FileImage, color: "#7C3AED" },
  gif: { icon: FileImage, color: "#7C3AED" },
  webp: { icon: FileImage, color: "#7C3AED" },
  svg: { icon: FileImage, color: "#7C3AED" },
  heic: { icon: FileImage, color: "#7C3AED" },
  // Audio
  mp3: { icon: FileAudio, color: "#0891B2" },
  wav: { icon: FileAudio, color: "#0891B2" },
  ogg: { icon: FileAudio, color: "#0891B2" },
  flac: { icon: FileAudio, color: "#0891B2" },
  // Video
  mp4: { icon: FileVideo, color: "#9333EA" },
  mov: { icon: FileVideo, color: "#9333EA" },
  avi: { icon: FileVideo, color: "#9333EA" },
  mkv: { icon: FileVideo, color: "#9333EA" },
  webm: { icon: FileVideo, color: "#9333EA" },
  // Archive
  zip: { icon: FileArchive, color: "#A16207" },
  rar: { icon: FileArchive, color: "#A16207" },
  "7z": { icon: FileArchive, color: "#A16207" },
  tar: { icon: FileArchive, color: "#A16207" },
  gz: { icon: FileArchive, color: "#A16207" },
  // Code / text
  txt: { icon: FileText, color: "#6B7280" },
  md: { icon: FileText, color: "#6B7280" },
  log: { icon: FileText, color: "#64748B" },
  json: { icon: FileCode, color: "#0EA5E9" },
  xml: { icon: FileCode, color: "#0EA5E9" },
  yml: { icon: FileCode, color: "#0EA5E9" },
  yaml: { icon: FileCode, color: "#0EA5E9" },
  toml: { icon: FileCode, color: "#0EA5E9" },
  js: { icon: FileCode, color: "#F59E0B" },
  jsx: { icon: FileCode, color: "#F59E0B" },
  ts: { icon: FileCode, color: "#0EA5E9" },
  tsx: { icon: FileCode, color: "#0EA5E9" },
  py: { icon: FileCode, color: "#1E90FF" },
  sh: { icon: FileCode, color: "#22C55E" },
  bash: { icon: FileCode, color: "#22C55E" },
  sql: { icon: FileCode, color: "#9333EA" },
  html: { icon: FileCode, color: "#F97316" },
  css: { icon: FileCode, color: "#3B82F6" },
  // E-books & Office (Apple/Google)
  epub: { icon: FileType, color: "#059669" },
  mobi: { icon: FileType, color: "#059669" },
  pages: { icon: FileText, color: "#1D4ED8" },
  numbers: { icon: FileSpreadsheet, color: "#16A34A" },
  key: { icon: Presentation, color: "#EA580C" },
  // CAD & vectors
  dwg: { icon: FileCode, color: "#DC2626" },
  dxf: { icon: FileCode, color: "#DC2626" },
  ai: { icon: FileImage, color: "#F97316" },
  psd: { icon: FileImage, color: "#0EA5E9" },
  indd: { icon: FileImage, color: "#EC4899" },
};

export function extensionFromUrl(url) {
  if (!url) return null;
  const clean = url.split("?")[0].split("#")[0];
  const m = clean.match(/\.([a-z0-9]{1,8})$/i);
  return m ? m[1].toLowerCase() : null;
}

export function extensionFromFilename(name) {
  if (!name) return null;
  const m = name.match(/\.([a-z0-9]{1,8})$/i);
  return m ? m[1].toLowerCase() : null;
}

export function getFileIcon(extOrUrl) {
  const ext = (extOrUrl || "").includes("/") || (extOrUrl || "").includes(".")
    ? (extensionFromUrl(extOrUrl) || extensionFromFilename(extOrUrl))
    : (extOrUrl || "").toLowerCase();
  if (ext && EXT_MAP[ext]) return { ...EXT_MAP[ext], ext };
  return { icon: FileGeneric, color: "#475569", ext: ext || null };
}

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";
export function absoluteFileUrl(u) {
  if (!u) return u;
  if (u.startsWith("http")) return u;
  return `${BACKEND}${u.startsWith("/") ? "" : "/"}${u}`;
}
