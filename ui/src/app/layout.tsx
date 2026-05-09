import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'RelyLoop',
  description: 'Open-source automated relevance tuning for enterprise search platforms',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
