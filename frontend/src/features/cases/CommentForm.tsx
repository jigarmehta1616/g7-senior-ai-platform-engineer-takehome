import { useState, type FormEvent } from "react";

import { api } from "../../api/client";
import { useToast } from "../../app/useToast";
import { Button } from "../../components";
import type { Comment } from "../../types/api";
import type { CommentFormProps } from "../../types/cases";

const MAX_LENGTH = 4000;

export function CommentForm({ caseId, onDone }: CommentFormProps) {
  const toast = useToast();
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState<Comment["visibility"]>("internal");
  const [submitting, setSubmitting] = useState(false);
  // One key per intent: a double-click or a network retry replays instead of duplicating.
  const [key, setKey] = useState(() => crypto.randomUUID());
  const blank = body.trim().length === 0;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (blank || submitting) return;
    setSubmitting(true);
    try {
      const { headers } = await api.addComment(caseId, body, visibility, key);
      toast.notify(headers.get("idempotency-replayed") ? "Duplicate suppressed (replayed)" : "Comment added");
      setBody("");
      setKey(crypto.randomUUID());
      onDone();
    } catch (error) {
      toast.fail(error); // the same key is kept, so retrying can't create a duplicate
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)} className="grid gap-2">
      <h3 className="font-semibold">Add comment</h3>
      <textarea required maxLength={MAX_LENGTH} rows={3} placeholder="Add a comment…" value={body}
        onChange={(e) => { setBody(e.target.value); }} />
      <p className="text-right text-xs text-muted">{body.length}/{MAX_LENGTH}</p>
      <select value={visibility} onChange={(e) => { setVisibility(e.target.value as Comment["visibility"]); }}>
        <option value="internal">Internal</option>
        <option value="public">Public (customer-visible)</option>
      </select>
      <Button type="submit" disabled={blank || submitting}>{submitting ? "Posting…" : "Post comment"}</Button>
    </form>
  );
}
