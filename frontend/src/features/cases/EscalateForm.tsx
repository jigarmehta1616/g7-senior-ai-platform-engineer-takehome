import { useState, type FormEvent } from "react";

import { ApiError, api } from "../../api/client";
import { useToast } from "../../app/useToast";
import { Button } from "../../components";
import { humanize } from "../../lib/format";
import type { EscalationReason } from "../../types/api";
import type { EscalateFormProps } from "../../types/cases";

const REASONS: readonly EscalationReason[] = ["customer_impact", "sla_breach_risk", "security_incident", "executive_request", "other"];
const NOTE_MAX = 500;

/** Two-step submit: escalation pages another team, so the first click only arms the button. */
export function EscalateForm({ caseId, etag, onDone }: EscalateFormProps) {
  const toast = useToast();
  const [reason, setReason] = useState<EscalationReason>("customer_impact");
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const noteMissing = reason === "other" && note.trim().length === 0;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (noteMissing || submitting || !etag) return;
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setConfirming(false);
    setSubmitting(true);
    try {
      await api.escalate(caseId, reason, note.trim(), etag);
      toast.notify("Escalated");
      setNote("");
      onDone();
    } catch (error) {
      toast.fail(error);
      if (error instanceof ApiError && error.status === 412) onDone(); // case changed: reload so the user can re-check
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)} className="grid gap-2">
      <h3 className="font-semibold">Escalate</h3>
      <select value={reason} onChange={(e) => { setReason(e.target.value as EscalationReason); setConfirming(false); }}>
        {REASONS.map((r) => (
          <option key={r} value={r}>{humanize(r)}</option>
        ))}
      </select>
      <input maxLength={NOTE_MAX} placeholder={reason === "other" ? "Note (required)" : "Note (optional)"} value={note}
        aria-invalid={noteMissing} onChange={(e) => { setNote(e.target.value); }} />
      {noteMissing && <p className="text-xs text-warn">A note is required when the reason is "other".</p>}
      <Button type="submit" variant={confirming ? "danger" : "primary"} disabled={noteMissing || submitting || !etag}>
        {submitting ? "Escalating…" : confirming ? `Confirm: escalate ${caseId}` : "Escalate case"}
      </Button>
    </form>
  );
}
