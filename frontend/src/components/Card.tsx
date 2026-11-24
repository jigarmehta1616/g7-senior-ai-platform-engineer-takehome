import type { CardProps } from "../types/ui";

export function Card({ children, className = "" }: CardProps) {
  return <section className={`rounded-xl border border-line bg-surface p-4 ${className}`}>{children}</section>;
}
