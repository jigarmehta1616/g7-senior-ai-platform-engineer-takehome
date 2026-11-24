import type { UsageChartProps } from "../../types/customers";

const WIDTH = 320;
const HEIGHT = 90;
const LABEL = 16;

/** Bar chart drawn with SVG geometry attributes (no inline CSS). */
export function UsageChart({ history }: UsageChartProps) {
  const max = Math.max(...history.map((u) => u.protectedTb), 1);
  const slot = WIDTH / Math.max(history.length, 1);
  return (
    <figure>
      <figcaption className="mb-1 text-xs text-muted">Protected TB by month</figcaption>
      <svg viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT + LABEL)}`} className="h-28 w-full max-w-md" role="img" aria-label="Protected TB by month">
        {history.map((u, i) => {
          const h = Math.max(4, (u.protectedTb / max) * HEIGHT);
          const x = i * slot + slot * 0.15;
          return (
            <g key={u.month}>
              <rect x={x} y={HEIGHT - h} width={slot * 0.7} height={h} rx={4} className="fill-brand">
                <title>{`${u.month}: ${String(u.protectedTb)} TB`}</title>
              </rect>
              <text x={x + slot * 0.35} y={HEIGHT + LABEL - 3} textAnchor="middle" className="fill-muted text-[10px]">
                {u.month}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
