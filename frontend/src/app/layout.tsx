import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'PDF Translate - Translate PDF Documents Easily',
  description: 'Translate large PDF files up to 3000 pages while preserving layout. Bilingual reading support.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
