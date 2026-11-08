"use client";

import { useEffect, useRef, useState } from "react";

export function usePoll<T>(fn: () => Promise<T>, ms: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const fnRef = useRef(fn);

  useEffect(() => {
    fnRef.current = fn;
  }, [fn]);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let loaded = false;

    const tick = async () => {
      // Skip polls in a hidden tab, but never the first load: a console opened in a
      // background tab (or captured by screen share) must not sit on "Loading...".
      if (loaded && typeof document !== "undefined" && document.hidden) {
        timer = setTimeout(() => void tick(), ms);
        return;
      }
      try {
        const next = await fnRef.current();
        if (stop) return;
        setData(next);
        loaded = true;
        setError(null);
        setStale(false);
      } catch (err) {
        if (stop) return;
        setError(err instanceof Error ? err.message : "Request failed");
        setStale(true);
      }
      if (!stop) timer = setTimeout(() => void tick(), ms);
    };

    void tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [ms]);

  return { data, error, stale: stale && data !== null };
}
