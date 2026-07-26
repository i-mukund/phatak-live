'use client';

import { useCallback, useEffect, useState } from 'react';

import { sendGateReport } from '@/lib/api';
import { formatCountdown } from '@/lib/format';
import type { GateReportResult } from '@/lib/types';

/**
 * Crowd reporting.
 *
 * One tap from someone at the gate is the only signal that sees freight. The
 * control therefore has to come *back* — a gate you cross twice a day is two
 * separate observations — while not inviting the same person to tap ten times
 * for one closure.
 *
 * The cooldown shown here is a courtesy, not the defence: the server enforces
 * its own per-client and per-IP limits, and decides what a report is allowed
 * to influence. So a cleared localStorage buys nothing.
 */
export function ReportBar({ slug }: { slug: string }) {
  const [result, setResult] = useState<GateReportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const report = useCallback(
    async (state: 'open' | 'closed') => {
      setBusy(true);
      setError(null);
      try {
        setResult(await sendGateReport(slug, state));
      } catch {
        setError('Could not send that — check your connection and try again.');
      } finally {
        setBusy(false);
      }
    },
    [slug],
  );

  // Tick down to the moment the server will accept another report, then
  // restore the buttons. Previously this state was terminal, which meant you
  // could never report the same gate twice.
  useEffect(() => {
    if (!result) return;
    // Fall back to a local cooldown when the server doesn't supply one, so the
    // control still recovers against an older backend. Never assume a field.
    const target = result.next_report_at
      ? new Date(result.next_report_at).getTime()
      : Date.now() + 600_000;
    const tick = () => {
      const remaining = Math.max(0, Math.round((target - Date.now()) / 1000));
      setSecondsLeft(remaining);
      if (remaining === 0) {
        setResult(null);
        setError(null);
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [result]);

  if (result) {
    const tone =
      result.outcome === 'unexplained'
        ? 'text-soon'
        : result.accepted === false
          ? 'text-ink-300'
          : 'text-open';
    return (
      <section className="px-5">
        <div className="card px-4 py-4 text-center animate-riseIn">
          <p className={`text-sm font-medium ${tone}`}>
            {result.message ?? 'Thanks — recorded.'}
          </p>
          {(result.corroborations ?? 0) > 1 && (
            <p className="mt-1 text-xs text-ink-400">
              {result.corroborations} people reported this — thank you.
            </p>
          )}
          {secondsLeft > 0 && (
            <p className="tnum mt-2 text-xs text-ink-500">
              You can report again in {formatCountdown(secondsLeft)}
            </p>
          )}
        </div>
      </section>
    );
  }

  return (
    <section className="px-5">
      <div className="card px-4 py-4">
        <p className="label">At the gate right now?</p>
        <p className="mt-1 text-sm text-ink-400">
          Tell us what you can actually see. Closures we didn&rsquo;t predict are
          usually freight.
        </p>
        {error && <p className="mt-2 text-xs text-closed">{error}</p>}
        <div className="mt-3 grid grid-cols-2 gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => report('open')}
            className="rounded-xl bg-open-dim px-3 py-3 text-sm font-semibold text-open transition active:scale-95 disabled:opacity-50"
          >
            It&rsquo;s open
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => report('closed')}
            className="rounded-xl bg-closed-dim px-3 py-3 text-sm font-semibold text-closed transition active:scale-95 disabled:opacity-50"
          >
            It&rsquo;s shut
          </button>
        </div>
      </div>
    </section>
  );
}
