'use client';

interface Props {
  error: string | null;
  isOffline: boolean;
  stale: boolean;
  degraded: boolean;
}

/** Honest, quiet warnings. Never a full-screen error over usable data. */
export function StatusBanner({ error, isOffline, stale, degraded }: Props) {
  const message = isOffline
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
      <p className="rounded-xl bg-soon/10 px-3.5 py-2.5 text-xs leading-relaxed text-soon">
        {message}
      </p>
    </div>
  );
}
