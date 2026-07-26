import type { Config } from 'tailwindcss';

/**
 * Apple-HIG-inspired tokens. The palette is deliberately tiny: one accent per
 * gate state, everything else is neutral. A status screen someone reads while
 * putting on their shoes should have no decoration competing with the answer.
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#08090c',
          900: '#0d0f13',
          800: '#14171d',
          700: '#1c2029',
          600: '#272c37',
          500: '#3a4150',
          400: '#69718a',
          300: '#98a0b3',
          200: '#c9cfdc',
          100: '#e8ebf2',
        },
        open: { DEFAULT: '#30d158', dim: '#0f3d21' },
        closed: { DEFAULT: '#ff453a', dim: '#43140f' },
        soon: { DEFAULT: '#ff9f0a', dim: '#432a05' },
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
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        pulseRing: 'pulseRing 2.4s cubic-bezier(0.24, 0.9, 0.32, 1) infinite',
        riseIn: 'riseIn 0.45s cubic-bezier(0.22, 1, 0.36, 1) both',
        shimmer: 'shimmer 1.6s infinite',
      },
    },
  },
  plugins: [],
};

export default config;
