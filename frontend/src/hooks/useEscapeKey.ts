import { useEffect } from "react";

/** Calls `onEscape` when the Escape key is pressed while the component is mounted. */
export function useEscapeKey(onEscape: () => void): void {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onEscape();
    };
    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
    };
  }, [onEscape]);
}
