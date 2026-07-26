import type { CrossingSummary } from '@/lib/types';

export function Header({ crossing }: { crossing: CrossingSummary }) {
  return (
    <header className="px-5 pt-6">
      <p className="label">Phatak Live</p>
      <h2 className="mt-1 text-[1.375rem] font-semibold leading-tight text-ink-100">
        {crossing.name}
      </h2>
      <p className="mt-0.5 text-sm text-ink-400">
        {crossing.line_name ?? [crossing.city, crossing.state].filter(Boolean).join(', ')}
      </p>
    </header>
  );
}
