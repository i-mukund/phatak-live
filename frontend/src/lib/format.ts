/**
 * Formatting helpers.
 *
 * Every timestamp from the API is absolute and IST-offset, so `new Date()`
 * parses it correctly in any device timezone. We then *display* in IST,
 * because the person reading this is standing in India.
 */

const IST_TIME = new Intl.DateTimeFormat('en-IN', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: true,
  timeZone: 'Asia/Kolkata',
});

const IST_TIME_WITH_SECONDS = new Intl.DateTimeFormat('en-IN', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: true,
  timeZone: 'Asia/Kolkata',
});

export function formatClock(iso: string | null | undefined, withSeconds = false): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return (withSeconds ? IST_TIME_WITH_SECONDS : IST_TIME).format(date);
}

/** `05:12` / `1:05:12` — a countdown you can read at a glance. */
export function formatCountdown(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = (n: number) => n.toString().padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

/** `4 min`, `1 hr 20 min` — for prose, not for counting down. */
export function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 60) return `${seconds} sec`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} hr` : `${hours} hr ${rest} min`;
}

export function relativeToNow(iso: string, now: number): string {
  const delta = (new Date(iso).getTime() - now) / 1000;
  if (Math.abs(delta) < 45) return 'just now';
  return delta > 0 ? `in ${formatDuration(delta)}` : `${formatDuration(-delta)} ago`;
}

export function titleCase(value: string): string {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

/**
 * Direction labels come from the crossing's own bracketing stations, so the UI
 * works unchanged for any crossing in India.
 */
export function directionLabel(
  direction: string,
  crossing?: { up_towards: string | null; down_towards: string | null },
): string {
  const towards = direction === 'up' ? crossing?.up_towards : crossing?.down_towards;
  if (direction !== 'up' && direction !== 'down') return 'Direction unknown';
  return towards ? `Towards ${towards}` : direction === 'up' ? 'Up line' : 'Down line';
}
