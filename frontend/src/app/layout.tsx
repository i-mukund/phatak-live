import type { Metadata, Viewport } from 'next';

import './globals.css';
import { RegisterServiceWorker } from '@/components/RegisterServiceWorker';

export const metadata: Metadata = {
  title: 'Phaatak — Siraspur Railway Crossing',
  description:
    'Should you leave now, or will the gate close before you get there? Live gate predictions for the Siraspur railway crossing.',
  applicationName: 'Phaatak',
  manifest: '/manifest.webmanifest',
  appleWebApp: {
    capable: true,
    title: 'Phaatak',
    // `default` lets iOS pick a legible status bar for the active theme;
    // `black-translucent` assumes a dark app and hides the text on light.
    statusBarStyle: 'default',
  },
  formatDetection: { telephone: false },
  icons: {
    icon: [
      { url: '/icon-192.png', sizes: '192x192', type: 'image/png' },
      { url: '/icon.svg', type: 'image/svg+xml' },
    ],
    apple: [{ url: '/apple-touch-icon.png', sizes: '180x180' }],
  },
  openGraph: {
    title: 'Phaatak',
    description: 'Know before you go. Live railway crossing predictions.',
    type: 'website',
  },
};

export const viewport: Viewport = {
  // Browser chrome follows the system theme too, so the status bar doesn't
  // sit as a black band above a white app (or vice versa).
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f6f7fa' },
    { media: '(prefers-color-scheme: dark)', color: '#08090c' },
  ],
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
  viewportFit: 'cover',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN">
      <body>
        <RegisterServiceWorker />
        {children}
      </body>
    </html>
  );
}
