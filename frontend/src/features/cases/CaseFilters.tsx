import { useState, type FormEvent } from "react";

import { Button, Field } from "../../components";
import type { Priority, SupportTier } from "../../types/api";
import type { CaseFilterValues, CaseFiltersProps } from "../../types/cases";
import { EMPTY_FILTERS, PRIORITIES, SAMPLE_QUESTION, TIERS } from "./filters";

export function CaseFilters({ onSearch }: CaseFiltersProps) {
  const [values, setValues] = useState<CaseFilterValues>(EMPTY_FILTERS);

  const set = <K extends keyof CaseFilterValues>(key: K, value: CaseFilterValues[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const togglePriority = (p: Priority) => {
    set("priorities", values.priorities.includes(p) ? values.priorities.filter((x) => x !== p) : [...values.priorities, p]);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSearch(values);
  };

  const runSampleQuestion = () => {
    setValues(SAMPLE_QUESTION);
    onSearch(SAMPLE_QUESTION);
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-3 rounded-xl border border-line bg-surface p-3">
      <fieldset className="flex items-center gap-3">
        <legend className="sr-only">Priority</legend>
        <span className="text-xs text-muted">Priority</span>
        {PRIORITIES.map((p) => (
          <label key={p} className="flex items-center gap-1 text-sm">
            <input type="checkbox" checked={values.priorities.includes(p)} onChange={() => { togglePriority(p); }} /> {p}
          </label>
        ))}
      </fieldset>
      <Field label="Status">
        <select value={values.status} onChange={(e) => { set("status", e.target.value); }}>
          <option value="open,in_progress,pending_customer">Active</option>
          <option value="open">Open only</option>
          <option value="resolved,closed">Resolved / closed</option>
          <option value="">Any</option>
        </select>
      </Field>
      <Field label="Tier">
        <select value={values.tier} onChange={(e) => { set("tier", e.target.value as SupportTier | ""); }}>
          <option value="">Any</option>
          {TIERS.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </Field>
      <Field label="Open > hours">
        <input className="w-28" type="number" min={0} max={8760} placeholder="e.g. 48" value={values.minOpenHours}
          onChange={(e) => { set("minOpenHours", e.target.value); }} />
      </Field>
      <Field label="Renews within days">
        <input className="w-28" type="number" min={1} max={730} placeholder="e.g. 90" value={values.renewalDays}
          onChange={(e) => { set("renewalDays", e.target.value); }} />
      </Field>
      <Field label="Sort">
        <select value={values.sort} onChange={(e) => { set("sort", e.target.value); }}>
          <option value="-openedAt">Newest</option>
          <option value="openedAt">Oldest</option>
          <option value="priority">Priority</option>
        </select>
      </Field>
      <div className="flex gap-2">
        <Button type="submit">Search</Button>
        <Button variant="ghost" title="Platinum customers with P1 cases open > 48h renewing within 90 days" onClick={runSampleQuestion}>
          Sample question
        </Button>
      </div>
    </form>
  );
}
