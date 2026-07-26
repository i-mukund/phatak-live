'use client';

interface Props {
  distance: number;
  armed: boolean;
  isRefreshing: boolean;
  threshold?: number;
}

/**
 * The spinner that rides down with the pull. It rotates in proportion to the
 * pull so the gesture feels directly connected to the control, rather than a
 * spinner that appears only after release.
 */
export function PullIndicator({ distance, armed, isRefreshing, threshold = 72 }: Props) {
  if (distance <= 0 && !isRefreshing) return null;

  const progress = Math.min(distance / threshold, 1);
  const rotation = isRefreshing ? 0 : progress * 270;

  return (
    <div
      className="pointer-events-none fixed inset-x-0 top-0 z-50 flex justify-center"
      style={{ transform: `translateY(${Math.max(distance - 34, 4)}px)` }}
      aria-hidden={!isRefreshing}
    >
      <div
        className={`flex h-9 w-9 items-center justify-center rounded-full border backdrop-blur-xl transition-colors ${
          armed || isRefreshing
            ? 'border-line/[0.18] bg-ink-800/90'
            : 'border-line/[0.10] bg-ink-900/80'
        }`}
      >
        <svg
          viewBox="0 0 24 24"
          className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''} ${
            armed || isRefreshing ? 'text-ink-100' : 'text-ink-400'
          }`}
          style={isRefreshing ? undefined : { transform: `rotate(${rotation}deg)` }}
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
        >
          <path
            d="M21 12a9 9 0 1 1-2.64-6.36"
            opacity={isRefreshing ? 1 : 0.35 + progress * 0.65}
          />
          <path d="M21 3v6h-6" opacity={isRefreshing ? 1 : 0.35 + progress * 0.65} />
        </svg>
      </div>
    </div>
  );
}
