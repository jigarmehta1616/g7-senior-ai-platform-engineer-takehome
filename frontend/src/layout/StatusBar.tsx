import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ResponseMeta } from "../types/client";

/** Shows the last API call, its correlation ID and the remaining rate-limit budget. */
export function StatusBar() {
  const [meta, setMeta] = useState<ResponseMeta | null>(null);
  useEffect(() => api.onResponse(setMeta), []);

  const rate = meta?.rateLimitRemaining == null ? "" : ` · rate limit remaining ${meta.rateLimitRemaining}`;
  return (
    <footer aria-live="polite" className="fixed inset-x-0 bottom-0 flex justify-between gap-3 border-t border-line bg-surface px-4 py-2 text-xs">
      <span>{meta ? `${meta.method} ${meta.path} → ${String(meta.status)}` : "Ready"}</span>
      <span className="text-muted">
        {meta && `correlation ${meta.correlationId}${rate} · `}Built by Jigar Mehta
      </span>
    </footer>
  );
}
