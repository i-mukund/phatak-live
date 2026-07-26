import type { Config } from 'tailwindcss';

/**
 * Apple-HIG-inspired tokens.
 *
 * Every colour resolves through a CSS variable so the whole palette flips with
 * `prefers-color-scheme` (see globals.css) without a single `dark:` variant in
 * the components. The `ink` scale is *semantic, not literal*: 950–800 are
 * surfaces and 400–100 are text, so in light mode the scale simply inverts.
 *
 * `<alpha-value>` keeps Tailwind's opacity modifiers (`bg-ink-900/70`) working
 * against variables, which is why the variables hold space-separated RGB
 * channels rather than hex.
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  // Theme follows the operating system. A manual toggle would add persisted
  // state and a settings surface to a one-screen glance app; the phone already
  // knows, and most people have it switching automatically at sunset.
  darkMode: 'media',
  theme: {
    extend: {
      colors: {
        ink: {
          950: 'rgb(var(--ink-950) / <alpha-value>)',
          900: 'rgb(var(--ink-900) / <alpha-value>)',
          800: 'rgb(var(--ink-800) / <alpha-value>)',
          700: 'rgb(var(--ink-700) / <alpha-value>)',
          600: 'rgb(var(--ink-600) / <alpha-value>)',
          500: 'rgb(var(--ink-500) / <alpha-value>)',
          400: 'rgb(var(--ink-400) / <alpha-value>)',
          300: 'rgb(var(--ink-300) / <alpha-value>)',
          200: 'rgb(var(--ink-200) / <alpha-value>)',
          100: 'rgb(var(--ink-100) / <alpha-value>)',
        },
        // Neutral overlays. Previously hard-coded `white/6%`, which is
        // invisible on a white background — the single biggest reason a
        // dark-only design does not "just work" in light mode.
        fill: 'rgb(var(--fill) / <alpha-value>)',
        line: 'rgb(var(--line) / <alpha-value>)',
        open: {
          DEFAULT: 'rgb(var(--open) / <alpha-value>)',
          dim: 'rgb(var(--open-dim) / <alpha-value>)',
        },
        closed: {
          DEFAULT: 'rgb(var(--closed) / <alpha-value>)',
          dim: 'rgb(var(--closed-dim) / <alpha-value>)',
        },
        soon: {
          DEFAULT: 'rgb(var(--soon) / <alpha-value>)',
          dim: 'rgb(var(--soon-dim) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: [
          '-apple-system', 'BlinkMacSystemFont', 'SF Pro Text', 'Segoe UI',
          'Inter', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif',
        ],
        mono: ['SF Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: {
        hero: ['4.25rem', { lineHeight: '1', letterSpacing: '-0.045em' }],
        countdown: ['3.5rem', { lineHeight: '1', letterSpacing: '-0.04em' }],
      },
      borderRadius: { xl2: '1.375rem' },
      boxShadow: {
        card: '0 1px 2px rgb(var(--shadow) / 0.04), 0 8px 24px -12px rgb(var(--shadow) / 0.10)',
      },
      keyframes: {
        pulseRing: {
          '0%': { transform: 'scale(0.92)', opacity: '0.65' },
          '70%': { transform: 'scale(1.35)', opacity: '0' },
          '100%': { transform: 'scale(1.35)', opacity: '0' },
        },
        riseIn: {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        pulseRing: 'pulseRing 2.4s cubic-bezier(0.24, 0.9, 0.32, 1) infinite',
        riseIn: 'riseIn 0.45s cubic-bezier(0.22, 1, 0.36, 1) both',
      },
    },
  },
  plugins: [],
};

export default config;
