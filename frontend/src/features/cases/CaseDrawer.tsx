import { useCallback } from "react";

import { ApiError, api } from "../../api/client";
import { useSession } from "../../app/useSession";
import { useToast } from "../../app/useToast";
import { Alert, Button, Drawer, Locked, PriorityLabel } from "../../components";
import { useLoader } from "../../hooks/useLoader";
import { formatDateTime, formatHours, humanize } from "../../lib/format";
import type { CaseDrawerProps } from "../../types/cases";
import { CommentForm } from "./CommentForm";
import { EscalateForm } from "./EscalateForm";

export function CaseDrawer({ caseId, onClose, onChanged }: CaseDrawerProps) {
  const { can } = useSession();
  const toast = useToast();
  const fetchCase = useCallback(() => api.getCase(caseId), [caseId]);
  const { data: result, error, reload } = useLoader(fetchCase, toast.fail);
  const detail = result?.data ?? null;
  const etag = result?.headers.get("etag") ?? "";

  const changed = useCallback(() => {
    reload();
    onChanged();
  }, [reload, onChanged]);

  if (!detail) {
    return (
      <Drawer label="Case details" onClose={onClose}>
        {error ? (
          <div className="space-y-3">
            <Alert tone="bad">
              Couldn't load {caseId}: {error instanceof ApiError ? (error.problem.detail ?? error.problem.title) : "unexpected error"}
            </Alert>
            <Button variant="ghost" onClick={reload}>Retry</Button>
          </div>
        ) : (
          <p className="text-muted">Loading…</p>
        )}
      </Drawer>
    );
  }

  const escalation = detail.escalation.level
    ? `L${String(detail.escalation.level)} → ${humanize(detail.escalation.targetTeam ?? "")}`
    : "none";

  return (
    <Drawer label="Case details" onClose={onClose}>
      <div className="space-y-4">
        <div>
          <p className="text-xs text-muted">{detail.id} · {detail.accountId} · ETag {etag}</p>
          {/* React renders this as text: case content is untrusted and may contain markup. */}
          <h2 className="mt-1 text-lg font-semibold break-words">{detail.subject}</h2>
          <p className="mt-1 text-sm">
            <PriorityLabel priority={detail.priority} /> · {humanize(detail.status)} · open {formatHours(detail.ageHours)} · escalation {escalation}
          </p>
        </div>
        <section>
          <h3 className="font-semibold">Comments ({detail.commentCount})</h3>
          {detail.comments.length === 0 && <p className="text-sm text-muted">No comments yet.</p>}
          {detail.comments.map((m) => (
            <div key={m.id} className="border-t border-line py-2">
              <p className="text-xs text-muted">{m.author} · {formatDateTime(m.createdAt)} · {m.visibility}</p>
              <p className="text-sm break-words whitespace-pre-wrap">{m.body}</p>
            </div>
          ))}
        </section>
        {can("cases:write") ? <CommentForm caseId={caseId} onDone={changed} /> : <Locked scope="cases:write" />}
        {can("cases:escalate") ? <EscalateForm caseId={caseId} etag={etag} onDone={changed} /> : <Locked scope="cases:escalate" />}
      </div>
    </Drawer>
  );
}
