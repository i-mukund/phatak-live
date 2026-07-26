import { NextResponse } from 'next/server';

import { API_BASE } from '@/lib/api';

export const dynamic = 'force-dynamic';

/** Proxies a crowd report ("the gate is actually shut right now") upstream. */
export async function POST(
  request: Request,
  context: { params: Promise<{ slug: string }> },
): Promise<NextResponse> {
  const { slug } = await context.params;
  const payload = await request.json().catch(() => null);
  if (!payload || (payload.state !== 'open' && payload.state !== 'closed')) {
    return NextResponse.json(
      { code: 'validation_error', message: 'state must be "open" or "closed"' },
      { status: 422 },
    );
  }

  try {
    const upstream = await fetch(
      `${API_BASE}/api/v1/crossings/${encodeURIComponent(slug)}/reports`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          state: payload.state,
          client_id: typeof payload.client_id === 'string' ? payload.client_id : null,
        }),
        signal: AbortSignal.timeout(8000),
      },
    );
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return NextResponse.json(
      { code: 'upstream_unavailable', message: 'Could not record your report.' },
      { status: 503 },
    );
  }
}
