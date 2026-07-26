'use client';

import { useEffect } from 'react';

/** Registers the service worker so the last answer survives a dead network. */
export function RegisterServiceWorker() {
  useEffect(() => {
    if (!('serviceWorker' in navigator) || process.env.NODE_ENV !== 'production') return;
    const register = () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {
        /* A failed SW registration must never break the page. */
      });
    };
    window.addEventListener('load', register);
    return () => window.removeEventListener('load', register);
  }, []);

  return null;
}
