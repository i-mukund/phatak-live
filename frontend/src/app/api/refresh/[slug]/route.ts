import { NextResponse } from 'next/server';

import { API_BASE } from '@/lib/api';

export const dynamic = 'force-dynamic';

/** Same-origin proxy for the pull-to-refresh endpoint. */
export async function POST(
  request: Request,
  context: { params: Promise<{ slug: string }> },
): Promise<NextResponse> {
  const { slug } = await context.params;
  const travel = new URL(request.url).searchParams.get('travel_seconds');
  const query = travel ? `?travel_seconds=${encodeURIComponent(travel)}` : '';

  try {
    const upstream = await fetch(
      `${API_BASE}/api/v1/crossings/${encodeURIComponent(slug)}/refresh${query}`,
      {
        method: 'POST',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
        // A refresh may wake a sleeping free-tier backend, so allow for a
        // cold start rather than failing the gesture at the usual 8s.
        signal: AbortSignal.timeout(60_000),
      },
    );
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    });
  } catch {
    return NextResponse.json(
      { code: 'upstream_unavailable', message: 'Could not reach the prediction service.' },
      { status: 503 },
    );
  }
}
