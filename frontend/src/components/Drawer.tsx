import { useEscapeKey } from "../hooks/useEscapeKey";
import type { DrawerProps } from "../types/ui";
import { Button } from "./Button";

/** Right-hand side panel. Closes on Escape or the × button. */
export function Drawer({ label, onClose, children }: DrawerProps) {
  useEscapeKey(onClose);
  return (
    <aside
      aria-label={label}
      className="fixed inset-y-0 right-0 z-20 w-full max-w-lg overflow-y-auto border-l border-line bg-surface p-4 shadow-2xl"
    >
      <Button variant="ghost" className="float-right" aria-label="Close" onClick={onClose}>
        ×
      </Button>
      {children}
    </aside>
  );
}
