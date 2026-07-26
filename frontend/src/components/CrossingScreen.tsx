'use client';

import { useState } from 'react';

import { ConfidenceBadge } from './ConfidenceBadge';
import { Footer } from './Footer';
import { Header } from './Header';
import { LeaveAdviceCard } from './LeaveAdviceCard';
import { ReportBar } from './ReportBar';
import { StatusBanner } from './StatusBanner';
import { StatusHero } from './StatusHero';
import { TodayHistory } from './TodayHistory';
import { TrainCard } from './TrainCard';
import { UpcomingList } from './UpcomingList';
import { useLiveStatus, useNow } from '@/lib/useLiveStatus';
import type { CrossingStatus } from '@/lib/types';

interface Props {
  slug: string;
  initial: CrossingStatus | null;
}

const DEFAULT_TRAVEL_SECONDS = 300;

export function CrossingScreen({ slug, initial }: Props) {
  const [travelSeconds, setTravelSeconds] = useState(DEFAULT_TRAVEL_SECONDS);
  const { status, error, isOffline } = useLiveStatus({
    slug,
    initial,
    travelSeconds,
  });
  const now = useNow(Boolean(status));

  if (!status) {
    return <Unavailable />;
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-lg flex-col gap-4 pb-2">
      <Header crossing={status.crossing} />
      <StatusBanner
        error={error}
        isOffline={isOffline}
        stale={status.data.stale}
        degraded={status.data.degraded}
      />
      <StatusHero status={status} now={now} />
      <LeaveAdviceCard
        advice={status.advice}
        travelSeconds={travelSeconds}
        onChange={setTravelSeconds}
      />
      <TrainCard train={status.approaching_train} crossing={status.crossing} now={now} />
      <ConfidenceBadge confidence={status.confidence} data={status.data} />
      <UpcomingList windows={status.upcoming} now={now} />
      <TodayHistory today={status.today} />
      <ReportBar slug={slug} />
      <Footer updatedAt={status.data.last_updated_at ?? status.generated_at} />
    </main>
  );
}

function Unavailable() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-lg flex-col items-center justify-center gap-3 px-8 text-center">
      <h1 className="text-2xl font-semibold text-ink-100">Can&rsquo;t reach the gate</h1>
      <p className="text-sm leading-relaxed text-ink-400">
        The prediction service is unavailable. Check your connection and pull to refresh — we
        don&rsquo;t guess when we have nothing to go on.
      </p>
    </main>
  );
}
