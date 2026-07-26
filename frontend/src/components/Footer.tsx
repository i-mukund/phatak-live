import { formatClock } from '@/lib/format';

export function Footer({ updatedAt }: { updatedAt: string | null }) {
  return (
    <footer className="px-5 pb-10 pt-2 text-center">
      <p className="tnum text-xs text-ink-500">
        Updated {formatClock(updatedAt, true)} IST · times are predictions, not guarantees
      </p>
      <p className="mt-1.5 text-xs text-ink-600">
        Never rely on this app at a level crossing. Obey the gate and the gatekeeper.
      </p>
    </footer>
  );
}
