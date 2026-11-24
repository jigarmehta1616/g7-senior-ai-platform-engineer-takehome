import type { BadgeProps, Tone } from "../types/ui";

const TONES: Record<Tone, string> = {
  neutral: "text-muted",
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
};

export function Badge({ tone = "neutral", children }: BadgeProps) {
  return <span className={`inline-block rounded-full bg-canvas px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>{children}</span>;
}
