const STORAGE_KEY = 'phaatak.client-id';

/**
 * A random per-browser id used only to deduplicate gate reports.
 *
 * Not an account, not a cookie, not tied to a person, and never sent anywhere
 * except with a report — where the server stores only a hash of it. Clearing
 * site data mints a new one, which is why the server also keeps an IP-based
 * ceiling as a backstop.
 */
export function getClientId(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const existing = window.localStorage.getItem(STORAGE_KEY);
    if (existing) return existing;
    const fresh =
      window.crypto?.randomUUID?.() ??
      `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    window.localStorage.setItem(STORAGE_KEY, fresh);
    return fresh;
  } catch {
    // Private mode or storage disabled: report anonymously and let the
    // server's IP ceiling do the work.
    return null;
  }
}
