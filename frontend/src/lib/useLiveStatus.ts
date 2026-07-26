'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchStatusFromProxy } from './api';
import type { CrossingStatus } from './types';

interface Options {
  slug: string;
  initial: CrossingStatus | null;
  travelSeconds?: number | null;
  intervalMs?: number;
}

interface LiveStatus {
  status: CrossingStatus | null;
  error: string | null;
  isRefreshing: boolean;
  isOffline: boolean;
  lastFetchedAt: number | null;
  refresh: () => void;
}

const MAX_BACKOFF_MS = 120_000;

/**
 * Polls the status endpoint.
 *
 * Three deliberate behaviours:
 *  - **Visibility-aware.** A phone in a pocket must not poll; we refresh
 *    immediately on wake instead, which is what the user actually wants.
 *  - **Exponential backoff on failure**, so a backend outage does not turn
 *    every open tab into a load generator.
 *  - **Never clears good data on error.** A stale answer with a warning beats
 *    a spinner when you are deciding whether to leave the house.
 */
export function useLiveStatus({
  slug,
  initial,
  travelSeconds,
  intervalMs = 15_000,
}: Options): LiveStatus {
  const [status, setStatus] = useState<CrossingStatus | null>(initial);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isOffline, setIsOffline] = useState(false);
  const [lastFetchedAt, setLastFetchedAt] = useState<number | null>(
    initial ? Date.now() : null,
  );

  const failures = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    setIsRefreshing(true);
    try {
      const data = await fetchStatusFromProxy(slug, travelSeconds, next.signal);
      setStatus(data);
      setError(null);
      failures.current = 0;
      setLastFetchedAt(Date.now());
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      failures.current += 1;
      setError('Could not reach the server. Showing the last known prediction.');
    } finally {
      setIsRefreshing(false);
    }
  }, [slug, travelSeconds]);

  useEffect(() => {
    let cancelled = false;

    const schedule = () => {
      if (cancelled) return;
      const backoff = Math.min(intervalMs * 2 ** failures.current, MAX_BACKOFF_MS);
      timer.current = setTimeout(run, failures.current > 0 ? backoff : intervalMs);
    };

    const run = async () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        schedule();
        return;
      }
      await load();
      schedule();
    };

    void run();

    const onVisible = () => {
      if (document.visibilityState === 'visible') void load();
    };
    const onOnline = () => {
      setIsOffline(false);
      failures.current = 0;
      void load();
    };
    const onOffline = () => setIsOffline(true);

    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    setIsOffline(!navigator.onLine);

    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
      controller.current?.abort();
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
    };
  }, [load, intervalMs]);

  return { status, error, isRefreshing, isOffline, lastFetchedAt, refresh: () => void load() };
}

/** Ticks once per second, purely to drive countdown re-renders. */
export function useNow(active = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return now;
}
