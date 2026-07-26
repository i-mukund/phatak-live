'use client';

import { directionLabel, formatClock, relativeToNow, titleCase } from '@/lib/format';
import type { ApproachingTrain, CrossingSummary } from '@/lib/types';

interface Props {
  train: ApproachingTrain | null;
  crossing: CrossingSummary;
  now: number;
}

export function TrainCard({ train, crossing, now }: Props) {
  if (!train) {
    return (
      <section className="px-5">
        <div className="card px-4 py-4">
          <p className="label">Approaching train</p>
          <p className="mt-1.5 text-sm text-ink-400">
            Nothing scheduled in the next two hours.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="px-5">
      <div className="card px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="label">Approaching train</p>
            <p className="mt-1.5 truncate text-base font-semibold text-ink-100">
              {train.train_name}
            </p>
            <p className="tnum mt-0.5 text-sm text-ink-400">
              {train.train_number} · {titleCase(train.train_class)}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className="tnum text-base font-semibold text-ink-100">
              {formatClock(train.pass_at)}
            </p>
            <p className="text-xs text-ink-400">{relativeToNow(train.pass_at, now)}</p>
          </div>
        </div>

        <div className="mt-3.5 flex flex-wrap gap-1.5 border-t border-line/[0.07] pt-3.5">
          <Chip>{directionLabel(train.direction, crossing)}</Chip>
          <Chip>{Math.round(train.speed_kmph)} km/h</Chip>
          {train.delay_minutes > 0 && (
            <Chip tone="warn">{train.delay_minutes} min late</Chip>
          )}
        </div>
      </div>
    </section>
  );
}

function Chip({ children, tone = 'plain' }: { children: React.ReactNode; tone?: 'plain' | 'warn' }) {
  const classes =
    tone === 'warn'
      ? 'bg-soon-dim text-soon'
      : 'bg-fill/[0.06] text-ink-300';
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${classes}`}>{children}</span>
  );
}
