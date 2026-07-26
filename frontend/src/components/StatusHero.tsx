'use client';

import { formatClock, formatCountdown, formatDuration } from '@/lib/format';
import type { CrossingStatus } from '@/lib/types';

const TONE = {
  open: {
    word: 'OPEN',
    dot: 'bg-open',
    ring: 'bg-open/30',
    text: 'text-open',
    glow: 'from-open/[0.14]',
  },
  closed: {
    word: 'CLOSED',
    dot: 'bg-closed',
    ring: 'bg-closed/30',
    text: 'text-closed',
    glow: 'from-closed/[0.16]',
  },
  closing_soon: {
    word: 'CLOSING',
    dot: 'bg-soon',
    ring: 'bg-soon/30',
    text: 'text-soon',
    glow: 'from-soon/[0.16]',
  },
} as const;

interface Props {
  status: CrossingStatus;
  now: number;
}

/**
 * The whole product in one screen: the state, and how long until it changes.
 * Everything below this fold is supporting evidence.
 */
export function StatusHero({ status, now }: Props) {
  const tone = TONE[status.state];
  const target =
    status.state === 'closed' ? status.current_closure?.open_at : status.next_closure?.close_at;
  const secondsLeft = target ? (new Date(target).getTime() - now) / 1000 : null;

  const caption =
    status.state === 'closed'
      ? 'Expected to reopen in'
      : status.next_closure
        ? 'Expected to close in'
        : 'No train expected soon';

  return (
    <section
      className="relative isolate overflow-hidden px-5 pb-9 pt-10 text-center"
      aria-live="polite"
      aria-atomic="true"
    >
      <div
        className={`pointer-events-none absolute inset-x-0 -top-24 -z-10 h-72 bg-gradient-to-b ${tone.glow} to-transparent blur-2xl`}
        aria-hidden
      />

      <div className="mb-5 flex items-center justify-center gap-2.5">
        <span className="relative flex h-2.5 w-2.5">
          <span className={`absolute inline-flex h-full w-full rounded-full ${tone.ring} animate-pulseRing`} />
          <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${tone.dot}`} />
        </span>
        <span className="label">Gate right now</span>
      </div>

      <h1 className={`font-sans text-hero font-bold ${tone.text} animate-riseIn`}>{tone.word}</h1>

      <div className="mt-7">
        <p className="label mb-2">{caption}</p>
        {secondsLeft !== null && secondsLeft > 0 ? (
          <p className="tnum text-countdown font-semibold text-ink-100">
            {formatCountdown(secondsLeft)}
          </p>
        ) : (
          <p className="text-2xl font-medium text-ink-300">
            {status.state === 'open' ? 'Clear for now' : 'Any moment'}
          </p>
        )}
      </div>

      <dl className="mx-auto mt-8 grid max-w-sm grid-cols-2 gap-3 text-left">
        <Stat
          label={status.state === 'closed' ? 'Reopens at' : 'Closes at'}
          value={formatClock(target)}
        />
        <Stat
          label={status.state === 'closed' ? 'Shut for' : 'Will stay shut'}
          value={
            status.state === 'closed'
              ? formatDuration(status.current_closure?.duration_seconds ?? 0)
              : formatDuration(status.next_closure?.duration_seconds ?? 0)
          }
        />
      </dl>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card px-4 py-3">
      <dt className="label">{label}</dt>
      <dd className="tnum mt-1 text-lg font-semibold text-ink-100">{value}</dd>
    </div>
  );
}
