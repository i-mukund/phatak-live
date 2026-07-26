'use client';

import { useState } from 'react';

import type { Confidence, DataQuality } from '@/lib/types';

interface Props {
  confidence: Confidence;
  data: DataQuality;
}

/**
 * Confidence is shown, not hidden, and it explains itself on tap.
 * We are telling someone whether to leave the house — an unexplained number
 * would be worse than no number.
 */
export function ConfidenceBadge({ confidence, data }: Props) {
  const [open, setOpen] = useState(false);
  const percent = Math.round(confidence.score * 100);
  const tone =
    percent >= 80 ? 'text-open' : percent >= 60 ? 'text-ink-100' : percent >= 40 ? 'text-soon' : 'text-closed';
  const notes = [...confidence.notes, ...data.notes].filter(
    (note, index, all) => all.indexOf(note) === index,
  );

  return (
    <section className="px-5">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="card flex w-full items-center gap-4 px-4 py-3.5 text-left transition active:scale-[0.99]"
      >
        <div className="flex-1">
          <p className="label">Confidence</p>
          <p className={`mt-0.5 text-base font-semibold capitalize ${tone}`}>
            {confidence.label} · {percent}%
          </p>
        </div>
        <Meter percent={percent} />
        <span className={`text-ink-400 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden>
          ▾
        </span>
      </button>

      {open && (
        <div className="card mt-2 space-y-3 px-4 py-4 text-sm text-ink-300 animate-riseIn">
          {notes.length > 0 && (
            <ul className="space-y-1.5">
              {notes.map((note) => (
                <li key={note} className="flex gap-2">
                  <span aria-hidden className="text-ink-500">
                    •
                  </span>
                  <span>{note}</span>
                </li>
              ))}
            </ul>
          )}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 border-t border-white/[0.06] pt-3 text-xs">
            <Row label="Source" value={data.providers_used.join(', ') || 'timetable'} />
            <Row label="Mode" value={data.degraded ? 'Fallback data' : 'Live data'} />
            {data.freight_risk > 0 && (
              <Row label="Freight risk" value={`${Math.round(data.freight_risk * 100)}%`} />
            )}
          </dl>
          <p className="text-xs leading-relaxed text-ink-500">
            Goods trains are not published by any public Indian Railways data source. Unexpected
            closures are usually freight.
          </p>
        </div>
      )}
    </section>
  );
}

function Meter({ percent }: { percent: number }) {
  const colour = percent >= 80 ? 'bg-open' : percent >= 60 ? 'bg-ink-200' : percent >= 40 ? 'bg-soon' : 'bg-closed';
  return (
    <div
      className="h-1.5 w-20 overflow-hidden rounded-full bg-white/10"
      role="meter"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Prediction confidence"
    >
      <div className={`h-full rounded-full ${colour} transition-all duration-500`} style={{ width: `${percent}%` }} />
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-ink-500">{label}</dt>
      <dd className="text-right text-ink-200">{value}</dd>
    </>
  );
}
