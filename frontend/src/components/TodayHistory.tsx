'use client';

import { formatClock, formatDuration } from '@/lib/format';
import type { TodaySummary } from '@/lib/types';

export function TodayHistory({ today }: { today: TodaySummary }) {
  return (
    <section className="px-5">
      <div className="card overflow-hidden">
        <div className="flex items-baseline justify-between px-4 pb-3 pt-4">
          <p className="label">Today so far</p>
          <p className="tnum text-xs text-ink-400">
            {today.closure_count} closure{today.closure_count === 1 ? '' : 's'} ·{' '}
            {formatDuration(today.total_closed_seconds)} shut
          </p>
        </div>

        {today.closures.length === 0 ? (
          <p className="px-4 pb-4 text-sm text-ink-400">
            No closures recorded yet today.
          </p>
        ) : (
          <ul className="divide-y divide-line/[0.07]">
            {today.closures.map((window) => (
              <li key={window.close_at} className="flex items-center gap-3 px-4 py-3">
                <div className="tnum w-[9.5rem] shrink-0 text-sm text-ink-200">
                  {formatClock(window.close_at)} → {formatClock(window.open_at)}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs text-ink-400">
                    {window.causes.map((cause) => cause.train_name).join(', ') || 'Unknown train'}
                  </p>
                </div>
                <span className="tnum shrink-0 rounded-full bg-fill/[0.06] px-2 py-1 text-xs text-ink-300">
                  {formatDuration(window.duration_seconds)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
