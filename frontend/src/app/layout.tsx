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
    statusBarStyle: 'black-translucent',
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
  themeColor: '#08090c',
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
  viewportFit: 'cover',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" className="dark">
      <body>
        <RegisterServiceWorker />
        {children}
      </body>
    </html>
  );
}
