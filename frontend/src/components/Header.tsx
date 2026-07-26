'use client';

import type { CrossingSummary } from '@/lib/types';

interface Props {
  crossing: CrossingSummary;
  onRefresh: () => void;
  isRefreshing: boolean;
}

export function Header({ crossing, onRefresh, isRefreshing }: Props) {
  return (
    <header className="flex items-start justify-between gap-3 px-5 pt-6">
      <div className="min-w-0">
        <p className="label">Phaatak</p>
        <h2 className="mt-1 text-[1.375rem] font-semibold leading-tight text-ink-100">
          {crossing.name}
        </h2>
        <p className="mt-0.5 text-sm text-ink-400">
          {crossing.line_name ?? [crossing.city, crossing.state].filter(Boolean).join(', ')}
        </p>
      </div>

      {/* Pull-to-refresh is the primary gesture on touch; this is the
          equivalent affordance for pointer devices and screen readers. */}
      <button
        type="button"
        onClick={onRefresh}
        disabled={isRefreshing}
        aria-label="Refresh status"
        className="mt-1 shrink-0 rounded-full border border-white/[0.08] bg-ink-900/70 p-2.5 text-ink-300 transition active:scale-90 disabled:opacity-50"
      >
        <svg
          viewBox="0 0 24 24"
          className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`}
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
        >
          <path d="M21 12a9 9 0 1 1-2.64-6.36" />
          <path d="M21 3v6h-6" />
        </svg>
      </button>
    </header>
  );
}
