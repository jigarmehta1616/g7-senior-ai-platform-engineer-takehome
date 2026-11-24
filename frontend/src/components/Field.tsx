import type { FieldProps } from "../types/ui";

/** A labelled form control. Wraps the input so clicking the label focuses it. */
export function Field({ label, children }: FieldProps) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      {children}
    </label>
  );
}
