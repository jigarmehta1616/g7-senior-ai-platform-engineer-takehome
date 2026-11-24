import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "../../api/client";
import { useToast } from "../../app/useToast";
import { Alert, Button, DataTable, PriorityLabel } from "../../components";
import { formatHours, humanize } from "../../lib/format";
import type { CaseSummary } from "../../types/api";
import type { CaseFilterValues, CasePageState } from "../../types/cases";
import type { Column } from "../../types/ui";
import { CaseDrawer } from "./CaseDrawer";
import { CaseFilters } from "./CaseFilters";
import { EMPTY_FILTERS, toQuery } from "./filters";

const COLUMNS: Column<CaseSummary>[] = [
  { header: "Case", cell: (c) => c.id },
  { header: "Customer", cell: (c) => c.account?.name ?? c.accountId },
  { header: "Tier", cell: (c) => c.account?.supportTier ?? "—" },
  { header: "Pri", cell: (c) => <PriorityLabel priority={c.priority} /> },
  { header: "Status", cell: (c) => humanize(c.status) },
  { header: "Age", cell: (c) => formatHours(c.ageHours), className: "tabular-nums" },
  { header: "Renewal", cell: (c) => c.account?.renewalDate ?? "—" },
  { header: "Esc", cell: (c) => (c.escalationLevel ? `L${String(c.escalationLevel)}` : "—") },
  { header: "Subject", cell: (c) => c.subject, className: "min-w-56 break-words" },
];

export function CasesPage() {
  const toast = useToast();
  const [query, setQuery] = useState(() => toQuery(EMPTY_FILTERS));
  const currentQuery = useRef(query);           // lets "Next page" ignore a response for old filters
  const [version, setVersion] = useState(0);
  const [page, setPage] = useState<CasePageState>({ rows: [], cursor: null });
  const [searching, setSearching] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [openCase, setOpenCase] = useState<string | null>(null);

  // First page: re-runs on every new search or refresh. Late responses from an older query are ignored.
  useEffect(() => {
    let active = true;
    api.listCases(query).then(
      ({ data }) => {
        if (!active) return;
        setPage({ rows: data.data, cursor: data.page.nextCursor });
        setSearching(false);
        setLoadError(null);
        if (data.degraded) toast.notify("Some sources are stale", data.staleSources.join(", "));
      },
      (error: unknown) => {
        if (!active) return;
        setSearching(false);
        setPage({ rows: [], cursor: null });
        setLoadError(error instanceof ApiError ? (error.problem.detail ?? error.problem.title) : "Unexpected error.");
        toast.fail(error);
      },
    );
    return () => {
      active = false;
    };
  }, [query, version, toast]);

  const search = useCallback((filters: CaseFilterValues) => {
    const next = toQuery(filters);
    currentQuery.current = next;
    setQuery(next);
    setSearching(true);
    setLoadError(null);
    setPage((prev) => ({ rows: prev.rows, cursor: null }));   // an old cursor must never be sent with new filters
  }, []);

  const refresh = useCallback(() => {
    setSearching(true);
    setVersion((v) => v + 1);
  }, []);

  const closeDrawer = useCallback(() => {
    setOpenCase(null);
  }, []);

  const loadMore = async () => {
    if (!page.cursor || searching) return;
    const forQuery = query;
    const params = new URLSearchParams(query);
    params.set("cursor", page.cursor);
    setLoadingMore(true);
    try {
      const { data } = await api.listCases(params);
      if (currentQuery.current !== forQuery) return;          // filters changed while this page was loading
      setPage((prev) => ({ rows: [...prev.rows, ...data.data], cursor: data.page.nextCursor }));
    } catch (error) {
      toast.fail(error);
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <div className="space-y-3">
      <CaseFilters onSearch={search} />
      <DataTable columns={COLUMNS} rows={page.rows} rowKey={(c) => c.id} onRowClick={(c) => { setOpenCase(c.id); }} empty={searching ? "Loading…" : loadError ? "Cases couldn't be loaded." : "No cases match."} />
      {loadError && !searching && (
        <div className="flex flex-wrap items-center gap-3">
          <Alert tone="bad">{loadError}</Alert>
          <Button variant="ghost" onClick={refresh}>Retry</Button>
        </div>
      )}
      {page.cursor && (
        <Button variant="ghost" disabled={loadingMore} onClick={() => void loadMore()}>
          Next page →
        </Button>
      )}
      {openCase && <CaseDrawer caseId={openCase} onClose={closeDrawer} onChanged={refresh} />}
    </div>
  );
}
