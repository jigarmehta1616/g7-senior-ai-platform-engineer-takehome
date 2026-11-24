/** State returned by `useLoader`. */
export interface LoaderState<T> {
  /** Last successfully loaded value (kept while a reload is in flight). */
  data: T | null;
  /** Error from the last attempt, or null after a success. */
  error: unknown;
  /** Re-run the loader. */
  reload: () => void;
}

/** A memoised async function that produces the data to show. `null` means "don't load". */
export type Loader<T> = (() => Promise<T>) | null;
