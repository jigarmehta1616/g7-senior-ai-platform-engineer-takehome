import type { CaseSummary, Priority, SupportTier } from "./api";

/** Form state for the case search. Relative values are converted to API params by `toQuery`. */
export interface CaseFilterValues {
  priorities: Priority[];
  status: string;
  tier: SupportTier | "";
  minOpenHours: string;
  renewalDays: string;
  sort: string;
}

export interface CaseFiltersProps {
  onSearch: (filters: CaseFilterValues) => void;
}

export interface CaseDrawerProps {
  caseId: string;
  onClose: () => void;
  onChanged: () => void;
}

export interface CommentFormProps {
  caseId: string;
  onDone: () => void;
}

export interface EscalateFormProps {
  caseId: string;
  etag: string;
  onDone: () => void;
}

/** The rows loaded so far and the cursor for the next page. */
export interface CasePageState {
  rows: CaseSummary[];
  cursor: string | null;
}
