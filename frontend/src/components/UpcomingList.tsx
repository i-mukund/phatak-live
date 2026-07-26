'use client';

import { formatClock, formatDuration, relativeToNow } from '@/lib/format';
import type { ClosureWindow } from '@/lib/types';

export function UpcomingList({ windows, now }: { windows: ClosureWindow[]; now: number }) {
  if (windows.length <= 1) return null;

  return (
    <section className="px-5">
      <div className="card overflow-hidden">
        <p className="label px-4 pb-3 pt-4">Later today</p>
        <ul className="divide-y divide-white/[0.05]">
          {windows.slice(1, 5).map((window) => (
            <li key={window.close_at} className="flex items-center gap-3 px-4 py-3">
              <div className="tnum w-24 shrink-0 text-sm font-medium text-ink-100">
                {formatClock(window.close_at)}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-ink-300">
                  {window.causes[0]?.train_name ?? 'Scheduled train'}
                </p>
                <p className="text-xs text-ink-500">{relativeToNow(window.close_at, now)}</p>
              </div>
              <span className="tnum shrink-0 text-xs text-ink-400">
                ~{formatDuration(window.duration_seconds)}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
