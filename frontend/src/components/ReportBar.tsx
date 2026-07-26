'use client';

import { useState } from 'react';

import { sendGateReport } from '@/lib/api';

/**
 * One tap from someone standing at the gate is worth more than any API we can
 * buy — it is the only signal that sees freight.
 */
export function ReportBar({ slug }: { slug: string }) {
  const [sent, setSent] = useState<'open' | 'closed' | null>(null);
  const [busy, setBusy] = useState(false);

  const report = async (state: 'open' | 'closed') => {
    setBusy(true);
    try {
      await sendGateReport(slug, state);
      setSent(state);
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <section className="px-5">
        <p className="card px-4 py-3.5 text-center text-sm text-ink-300">
          Thanks — recorded. This makes tomorrow&rsquo;s prediction better.
        </p>
      </section>
    );
  }

  return (
    <section className="px-5">
      <div className="card px-4 py-4">
        <p className="label">At the gate right now?</p>
        <p className="mt-1 text-sm text-ink-400">Tell us what you can actually see.</p>
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
