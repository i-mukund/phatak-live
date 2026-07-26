import { NextResponse } from 'next/server';

import { API_BASE } from '@/lib/api';

export const dynamic = 'force-dynamic';

/**
 * Same-origin proxy for the status endpoint.
 *
 * Keeps the browser off cross-origin requests (no preflight on a flaky mobile
 * connection), hides the backend URL, and gives us one place to add edge
 * caching later.
 */
export async function GET(
  request: Request,
  context: { params: Promise<{ slug: string }> },
): Promise<NextResponse> {
  const { slug } = await context.params;
  const travel = new URL(request.url).searchParams.get('travel_seconds');
  const query = travel ? `?travel_seconds=${encodeURIComponent(travel)}` : '';

  try {
    const upstream = await fetch(
      `${API_BASE}/api/v1/crossings/${encodeURIComponent(slug)}/status${query}`,
      {
        cache: 'no-store',
        headers: { Accept: 'application/json' },
        signal: AbortSignal.timeout(8000),
      },
    );
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'public, max-age=5, stale-while-revalidate=30',
      },
    });
  } catch {
    return NextResponse.json(
      { code: 'upstream_unavailable', message: 'The prediction service is unreachable.' },
      { status: 503 },
    );
  }
}
