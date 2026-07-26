import { CrossingScreen } from '@/components/CrossingScreen';
import { DEFAULT_SLUG, fetchStatus } from '@/lib/api';
import type { CrossingStatus } from '@/lib/types';

/**
 * Server-rendered first paint.
 *
 * The answer should already be on screen when the page appears — this is read
 * on a phone, on a mobile network, by someone with their shoes half on. If the
 * backend is unreachable at render time we still ship the shell and let the
 * client retry.
 */
export const dynamic = 'force-dynamic';
export const revalidate = 0;

export default async function HomePage() {
  let initial: CrossingStatus | null = null;
  try {
    initial = await fetchStatus(DEFAULT_SLUG, 300);
  } catch {
    initial = null;
  }
  return <CrossingScreen slug={DEFAULT_SLUG} initial={initial} />;
}
