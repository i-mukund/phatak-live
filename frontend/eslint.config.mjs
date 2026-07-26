import { FlatCompat } from '@eslint/eslintrc';

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

/**
 * Flat config. `next lint` is deprecated as of Next 15.5, so we drive ESLint
 * directly and keep the Next + TypeScript rule sets via the compat shim.
 */
const config = [
  { ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts'] },
  ...compat.extends('next/core-web-vitals', 'next/typescript'),
];

export default config;
