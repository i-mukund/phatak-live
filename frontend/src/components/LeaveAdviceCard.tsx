'use client';

import { formatClock } from '@/lib/format';
import type { LeaveAdvice } from '@/lib/types';

const PRESETS = [180, 300, 600, 900] as const;

interface Props {
  advice: LeaveAdvice | null;
  travelSeconds: number;
  onChange: (seconds: number) => void;
}

/** The literal product question, made interactive. */
export function LeaveAdviceCard({ advice, travelSeconds, onChange }: Props) {
  const tone =
    advice?.verdict === 'wait'
      ? { label: "You'll be waiting", classes: 'text-closed' }
      : advice?.verdict === 'tight'
        ? { label: 'Cutting it fine', classes: 'text-soon' }
        : { label: 'Go now', classes: 'text-open' };

  return (
    <section className="px-5">
      <div className="card px-4 py-4">
        <p className="label">If I leave now</p>

        <p className={`mt-1.5 text-lg font-semibold ${tone.classes}`}>{tone.label}</p>
        <p className="mt-1 text-sm leading-relaxed text-ink-300">
          {advice?.reason ?? 'Pick how long it takes you to reach the gate.'}
        </p>

        <div className="mt-4">
          <div className="mb-2 flex items-baseline justify-between">
            <span className="label">My travel time</span>
            {advice && (
              <span className="tnum text-xs text-ink-400">
                arrive ~{formatClock(advice.arrival_at)}
              </span>
            )}
          </div>
          <div
            className="grid grid-cols-4 gap-1.5"
            role="radiogroup"
            aria-label="How long it takes you to reach the crossing"
          >
            {PRESETS.map((seconds) => {
              const active = seconds === travelSeconds;
              return (
                <button
                  key={seconds}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => onChange(seconds)}
                  className={`tnum rounded-xl px-2 py-2.5 text-sm font-medium transition active:scale-95 ${
                    active
                      ? 'bg-ink-100 text-ink-950'
                      : 'bg-white/[0.06] text-ink-300 hover:bg-white/[0.1]'
                  }`}
                >
                  {seconds / 60} min
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
