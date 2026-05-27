/*
 * Iter38d — Resizable vertical bar between left (list) and right (messages)
 * panels. Works on both desktop (mouse) and mobile (touch).
 *
 * Usage:
 *   const { leftWidth, dragHandlers, isCollapsed, toggleCollapsed } =
 *     useResizablePanel({ storageKey: "internal_chat_split", initial: 320, min: 200, max: 600 });
 *
 *   <div style={{ width: leftWidth }} className={isCollapsed ? "hidden" : ""}>...left panel...</div>
 *   <div {...dragHandlers} className="w-1.5 cursor-col-resize bg-slate-200 hover:bg-sawali-blue touch-none" />
 *   <div className="flex-1">...right panel (messages)...</div>
 *   {on mobile, render a small toggle button to show/hide the list}
 */
import { useCallback, useEffect, useRef, useState } from "react";

export function useResizablePanel({
  storageKey,
  initial = 320,
  min = 200,
  max = 600,
}) {
  const [leftWidth, setLeftWidth] = useState(() => {
    try {
      const v = parseInt(localStorage.getItem(storageKey) || "", 10);
      if (v && v >= min && v <= max) return v;
    } catch { /* noop */ }
    return initial;
  });
  const [isCollapsed, setIsCollapsed] = useState(() => {
    try {
      return localStorage.getItem(`${storageKey}_collapsed`) === "1";
    } catch { return false; }
  });

  const draggingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(leftWidth);

  const onPointerDown = useCallback((e) => {
    draggingRef.current = true;
    startXRef.current = e.touches ? e.touches[0].clientX : e.clientX;
    startWidthRef.current = leftWidth;
    e.preventDefault();
  }, [leftWidth]);

  const onPointerMove = useCallback((e) => {
    if (!draggingRef.current) return;
    const x = e.touches ? e.touches[0].clientX : e.clientX;
    const dx = x - startXRef.current;
    const newW = Math.max(min, Math.min(max, startWidthRef.current + dx));
    setLeftWidth(newW);
  }, [min, max]);

  const onPointerUp = useCallback(() => {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    try { localStorage.setItem(storageKey, String(leftWidth)); } catch { /* noop */ }
  }, [leftWidth, storageKey]);

  useEffect(() => {
    window.addEventListener("mousemove", onPointerMove);
    window.addEventListener("mouseup", onPointerUp);
    window.addEventListener("touchmove", onPointerMove, { passive: false });
    window.addEventListener("touchend", onPointerUp);
    return () => {
      window.removeEventListener("mousemove", onPointerMove);
      window.removeEventListener("mouseup", onPointerUp);
      window.removeEventListener("touchmove", onPointerMove);
      window.removeEventListener("touchend", onPointerUp);
    };
  }, [onPointerMove, onPointerUp]);

  const toggleCollapsed = useCallback(() => {
    setIsCollapsed((v) => {
      try { localStorage.setItem(`${storageKey}_collapsed`, v ? "0" : "1"); } catch { /* noop */ }
      return !v;
    });
  }, [storageKey]);

  const dragHandlers = {
    onMouseDown: onPointerDown,
    onTouchStart: onPointerDown,
  };

  return { leftWidth, dragHandlers, isCollapsed, toggleCollapsed, setLeftWidth };
}

// Drag handle component for easy reuse
export function DragHandle({ dragHandlers, "data-testid": testid }) {
  return (
    <div
      {...dragHandlers}
      data-testid={testid || "chat-resize-handle"}
      role="separator"
      aria-orientation="vertical"
      title="Glissez pour redimensionner"
      className="hidden md:flex items-center justify-center w-1.5 hover:w-2 cursor-col-resize bg-slate-200 hover:bg-sawali-blue active:bg-sawali-blue transition-all select-none touch-none"
    >
      <div className="h-8 w-0.5 bg-slate-400 rounded" />
    </div>
  );
}
