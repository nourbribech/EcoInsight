import { useState, useEffect } from 'react';

/*a custom hook that fetches from an endpoint on a repeating interval and
 gives components live data, loading state, and error state without 
 each component reimplementing fetch + setInterval + cleanup.*/

interface PollingResult<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

export function usePolling<T>(url:string, intervalMs:number):PollingResult<T> {
  // The type parameters matter: bare useState(null) infers the type as
  // literally `null`, so setData(json) is an error and `data` is useless to
  // the caller even though the hook is declared generic.
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const json = await res.json();
        if (!cancelled) {
          setData(json);
          setError(null);
          setLoading(false);
        }
      } catch (err: unknown) {
        // TS types a catch binding as `unknown`, because JS lets you throw
        // anything — a string, a number, undefined. Narrow before using it.
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      }
    }

    fetchData(); // fire immediately, don't wait for the first interval tick
    const id = setInterval(fetchData, intervalMs);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [url, intervalMs]);

  return { data, error, loading };
}