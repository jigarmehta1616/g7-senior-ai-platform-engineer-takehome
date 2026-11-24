import { useCallback, useEffect, useState } from "react";

import type { Loader, LoaderState } from "../types/hooks";

/**
 * Runs `load` when it changes (or when `reload` is called) and exposes the result.
 *
 * State is only set from the promise callbacks, never synchronously inside the effect, and
 * responses that arrive after the component re-rendered with a newer loader are ignored.
 * `load` and `onError` must be stable (wrap them in useCallback).
 */
export function useLoader<T>(load: Loader<T>, onError?: (error: unknown) => void): LoaderState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!load) return;
    let active = true;
    load().then(
      (value) => {
        if (!active) return;
        setData(value);
        setError(null);
      },
      (err: unknown) => {
        if (!active) return;
        setError(err);
        onError?.(err);
      },
    );
    return () => {
      active = false;
    };
  }, [load, version, onError]);

  const reload = useCallback(() => {
    setVersion((v) => v + 1);
  }, []);

  return { data, error, reload };
}
