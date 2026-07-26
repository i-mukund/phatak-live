'use client';

interface Props {
  error: string | null;
  isOffline: boolean;
  stale: boolean;
  degraded: boolean;
  /** Transient message from a pull that did not fetch — takes precedence,
   *  because the user just asked a question and deserves the answer. */
  notice?: string | null;
}

/** Honest, quiet warnings. Never a full-screen error over usable data. */
export function StatusBanner({ error, isOffline, stale, degraded, notice }: Props) {
  const message = notice
    ? notice
    : isOffline
    ? "You're offline — showing the last prediction we downloaded."
    : error
      ? error
      : stale
        ? 'Live data is delayed; this prediction may drift.'
        : degraded
          ? 'No live train feed right now — predicting from the timetable.'
          : null;

  if (!message) return null;

  return (
    <div className="px-5" role="status">
      <p className="rounded-xl bg-soon-dim px-3.5 py-2.5 text-xs leading-relaxed text-soon">
        {message}
      </p>
    </div>
  );
}
