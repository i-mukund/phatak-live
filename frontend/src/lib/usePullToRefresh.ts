'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

interface Options {
  onRefresh: () => Promise<void>;
  /** Pull distance, in px, that arms the refresh. */
  threshold?: number;
  disabled?: boolean;
}

interface PullState {
  /** Visual offset in px, already damped. */
  distance: number;
  /** Past the threshold — releasing now will refresh. */
  armed: boolean;
  isRefreshing: boolean;
  isPulling: boolean;
}

const MAX_PULL = 120;
const RESISTANCE = 0.5;

/**
 * Native-feeling pull-to-refresh.
 *
 * Deliberate choices:
 *  - Only engages at `scrollTop === 0` **and** when the first movement is
 *    downward, so it never steals a normal upward scroll.
 *  - Rubber-band damping: real distance is halved and capped, matching the
 *    resistance iOS applies. A 1:1 pull feels broken.
 *  - `touch-action: pan-y` stays on the page; we call `preventDefault` only
 *    once actually pulling, so the browser's own overscroll doesn't fight us.
 *  - A short haptic tick at the arm threshold, where supported. That's the
 *    moment the user needs to know the gesture registered.
 */
export function usePullToRefresh({
  onRefresh,
  threshold = 72,
  disabled = false,
}: Options): PullState {
  const [distance, setDistance] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isPulling, setIsPulling] = useState(false);

  const startY = useRef(0);
  const active = useRef(false);
  const armedRef = useRef(false);
  const refreshingRef = useRef(false);

  const armed = distance >= threshold;

  const finish = useCallback(async () => {
    refreshingRef.current = true;
    setIsRefreshing(true);
    setDistance(threshold);
    try {
      await onRefresh();
    } finally {
      refreshingRef.current = false;
      setIsRefreshing(false);
      setDistance(0);
    }
  }, [onRefresh, threshold]);

  useEffect(() => {
    if (disabled) return;

    const onTouchStart = (event: TouchEvent) => {
      if (refreshingRef.current) return;
      if (window.scrollY > 0) return;
      const touch = event.touches[0];
      if (!touch) return;
      startY.current = touch.clientY;
      active.current = true;
      armedRef.current = false;
    };

    const onTouchMove = (event: TouchEvent) => {
      if (!active.current || refreshingRef.current) return;
      const touch = event.touches[0];
      if (!touch) return;

      const delta = touch.clientY - startY.current;
      if (delta <= 0) {
        // Upward movement: hand the gesture back to the browser.
        active.current = false;
        setDistance(0);
        setIsPulling(false);
        return;
      }
      if (window.scrollY > 0) return;

      event.preventDefault();
      const damped = Math.min(delta * RESISTANCE, MAX_PULL);
      setDistance(damped);
      setIsPulling(true);

      if (!armedRef.current && damped >= threshold) {
        armedRef.current = true;
        navigator.vibrate?.(8);
      }
    };

    const onTouchEnd = () => {
      if (!active.current) return;
      active.current = false;
      setIsPulling(false);
      if (armedRef.current && !refreshingRef.current) {
        void finish();
      } else {
        setDistance(0);
      }
      armedRef.current = false;
    };

    // `passive: false` is required for preventDefault to be honoured on move.
    window.addEventListener('touchstart', onTouchStart, { passive: true });
    window.addEventListener('touchmove', onTouchMove, { passive: false });
    window.addEventListener('touchend', onTouchEnd, { passive: true });
    window.addEventListener('touchcancel', onTouchEnd, { passive: true });

    return () => {
      window.removeEventListener('touchstart', onTouchStart);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('touchend', onTouchEnd);
      window.removeEventListener('touchcancel', onTouchEnd);
    };
  }, [disabled, finish, threshold]);

  return { distance, armed, isRefreshing, isPulling };
}
