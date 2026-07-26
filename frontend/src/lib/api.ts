import { getClientId } from './clientId';
import type { CrossingStatus, GateReportResult, RefreshResult } from './types';

/**
 * Server-side base URL. Browser requests go through the Next route handler at
 * `/api/status/[slug]` instead, so the app is same-origin (no CORS preflight on
 * a mobile network) and can be cached at the edge.
 */
export const API_BASE =
  process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

export const DEFAULT_SLUG = process.env.NEXT_PUBLIC_DEFAULT_CROSSING ?? 'siraspur';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function statusUrl(slug: string, travelSeconds?: number | null): string {
  const query = travelSeconds ? `?travel_seconds=${travelSeconds}` : '';
  return `${API_BASE}/api/v1/crossings/${slug}/status${query}`;
}

/** Server-side fetch used to render the first paint. */
export async function fetchStatus(
  slug: string,
  travelSeconds?: number | null,
): Promise<CrossingStatus> {
  const response = await fetch(statusUrl(slug, travelSeconds), {
    // The backend already caches for 15 s; re-caching here would only add lag.
    cache: 'no-store',
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    throw new ApiError(`Status request failed (${response.status})`, response.status);
  }
  return (await response.json()) as CrossingStatus;
}

/** Client-side fetch through the same-origin proxy. */
export async function fetchStatusFromProxy(
  slug: string,
  travelSeconds?: number | null,
  signal?: AbortSignal,
): Promise<CrossingStatus> {
  const query = travelSeconds ? `?travel_seconds=${travelSeconds}` : '';
  const response = await fetch(`/api/status/${slug}${query}`, {
    signal,
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    throw new ApiError(`Status request failed (${response.status})`, response.status);
  }
  return (await response.json()) as CrossingStatus;
}

/** Pull-to-refresh: asks the server for the freshest *available* status. */
export async function requestRefresh(
  slug: string,
  travelSeconds?: number | null,
  signal?: AbortSignal,
): Promise<RefreshResult> {
  const query = travelSeconds ? `?travel_seconds=${travelSeconds}` : '';
  const response = await fetch(`/api/refresh/${slug}${query}`, {
    method: 'POST',
    signal,
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    throw new ApiError(`Refresh failed (${response.status})`, response.status);
  }
  return (await response.json()) as RefreshResult;
}

export async function sendGateReport(
  slug: string,
  state: 'open' | 'closed',
): Promise<GateReportResult> {
  const response = await fetch(`/api/report/${slug}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ state, client_id: getClientId() }),
  });
  if (!response.ok) {
    throw new ApiError(`Report failed (${response.status})`, response.status);
  }
  return (await response.json()) as GateReportResult;
}
