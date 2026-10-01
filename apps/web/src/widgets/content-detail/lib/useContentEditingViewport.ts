import { useEffect, useState } from "react";

export function useContentEditingViewport() {
  const [viewport, setViewport] = useState<{ top: number; height: number; bottomInset: number }>();
  useEffect(() => {
    function measure() {
      const visible = window.visualViewport;
      const focused = document.activeElement;
      const isEditing = (focused instanceof HTMLTextAreaElement || focused instanceof HTMLInputElement) &&
        !!focused.closest("[data-content-detail]");
      const hasKeyboard = !!visible && window.innerHeight - visible.height > 120 && isEditing;
      setViewport(hasKeyboard ? {
        top: visible.offsetTop, height: visible.height,
        bottomInset: Math.max(0, window.innerHeight - visible.offsetTop - visible.height),
      } : undefined);
    }
    const handleFocusChanged = () => requestAnimationFrame(measure);
    window.visualViewport?.addEventListener("resize", measure);
    window.visualViewport?.addEventListener("scroll", measure);
    document.addEventListener("focusin", handleFocusChanged);
    document.addEventListener("focusout", handleFocusChanged);
    return () => {
      window.visualViewport?.removeEventListener("resize", measure);
      window.visualViewport?.removeEventListener("scroll", measure);
      document.removeEventListener("focusin", handleFocusChanged);
      document.removeEventListener("focusout", handleFocusChanged);
    };
  }, []);
  return viewport;
}
