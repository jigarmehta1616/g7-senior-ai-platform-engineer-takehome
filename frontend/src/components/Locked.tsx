import type { LockedProps } from "../types/ui";

/** Shown in place of data or actions the signed-in user's scopes don't allow. */
export function Locked({ scope }: LockedProps) {
  return <p className="text-sm text-muted">🔒 requires {scope}</p>;
}
