'use client';

import { useCallback, useEffect, useState } from 'react';

import { ConfidenceBadge } from './ConfidenceBadge';
import { Footer } from './Footer';
import { Header } from './Header';
import { LeaveAdviceCard } from './LeaveAdviceCard';
import { PullIndicator } from './PullIndicator';
import { ReportBar } from './ReportBar';
import { StatusBanner } from './StatusBanner';
import { StatusHero } from './StatusHero';
import { TodayHistory } from './TodayHistory';
import { TrainCard } from './TrainCard';
import { UpcomingList } from './UpcomingList';
import { usePullToRefresh } from '@/lib/usePullToRefresh';
import { useLiveStatus, useNow } from '@/lib/useLiveStatus';
import type { CrossingStatus } from '@/lib/types';

interface Props {
  slug: string;
  initial: CrossingStatus | null;
}

const DEFAULT_TRAVEL_SECONDS = 300;
const PULL_THRESHOLD = 72;

export function CrossingScreen({ slug, initial }: Props) {
  const [travelSeconds, setTravelSeconds] = useState(DEFAULT_TRAVEL_SECONDS);
  const [notice, setNotice] = useState<string | null>(null);

  const { status, error, isOffline, isRefreshing, pullRefresh } = useLiveStatus({
    slug,
    initial,
    travelSeconds,
  });
  const now = useNow(Boolean(status));

  const handleRefresh = useCallback(async () => {
    const message = await pullRefresh();
    setNotice(message);
  }, [pullRefresh]);

  // The notice explains why a pull didn't fetch anything; it should not linger.
  useEffect(() => {
    if (!notice) return;
    const id = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(id);
  }, [notice]);

  const pull = usePullToRefresh({
    onRefresh: handleRefresh,
    threshold: PULL_THRESHOLD,
    disabled: !status,
  });

  if (!status) {
    return <Unavailable />;
  }

  return (
    <>
      <PullIndicator
        distance={pull.distance}
        armed={pull.armed}
        isRefreshing={pull.isRefreshing}
        threshold={PULL_THRESHOLD}
      />
      <main
        className="mx-auto flex min-h-dvh w-full max-w-lg flex-col gap-4 pb-2"
        style={{
          transform: `translateY(${pull.distance}px)`,
          // Follow the finger 1:1 while pulling; ease back only on release.
          transition: pull.isPulling ? 'none' : 'transform 0.32s cubic-bezier(0.22,1,0.36,1)',
        }}
      >
        <Header
          crossing={status.crossing}
          onRefresh={handleRefresh}
          isRefreshing={isRefreshing}
        />
        <StatusBanner
          error={error}
          isOffline={isOffline}
          stale={status.data.stale}
          degraded={status.data.degraded}
          notice={notice}
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
    </>
  );
}

function Unavailable() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-lg flex-col items-center justify-center gap-3 px-8 text-center">
      <h1 className="text-2xl font-semibold text-ink-100">Can&rsquo;t reach the gate</h1>
      <p className="text-sm leading-relaxed text-ink-400">
        The prediction service is unavailable. Check your connection and try again — we
        don&rsquo;t guess when we have nothing to go on.
      </p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="mt-2 rounded-xl bg-white/[0.08] px-5 py-2.5 text-sm font-medium text-ink-100 transition active:scale-95"
      >
        Try again
      </button>
    </main>
  );
}
