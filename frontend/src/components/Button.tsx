import type { ButtonProps, ButtonVariant } from "../types/ui";

const BASE =
  "inline-flex items-center justify-center gap-1 rounded-md px-3 py-1.5 text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-50";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-brand text-brand-ink hover:opacity-90",
  ghost: "border border-line bg-transparent text-ink hover:bg-canvas",
  danger: "bg-bad text-brand-ink hover:opacity-90",
};

export function Button({ variant = "primary", className = "", type = "button", ...props }: ButtonProps) {
  return <button type={type} className={`${BASE} ${VARIANTS[variant]} ${className}`} {...props} />;
}
