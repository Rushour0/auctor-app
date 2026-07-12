import type React from "react";
import { useEffect, useState } from "react";

export type FetchState<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
};

/**
 * Reusable data-fetch hook. Runs `fn` on mount and whenever `deps` change,
 * tracking loading/error state and guarding against setState after unmount.
 * Call `reload()` to re-run `fn` without changing `deps`.
 */
export function useFetch<T>(fn: () => Promise<T>, deps: React.DependencyList): FetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fn()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = () => setNonce((n) => n + 1);

  return { data, loading, error, reload };
}
