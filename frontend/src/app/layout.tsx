import type { Metadata } from 'next';
import { ClerkProvider } from '@clerk/nextjs';
import './globals.css';

export const metadata: Metadata = {
  title: 'LingoDoc - PDF Translation Service',
  description: 'AI-powered PDF translation for review and reading, with bilingual output and support for larger files.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const clerkPublishableKey = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        {clerkPublishableKey ? (
          <ClerkProvider publishableKey={clerkPublishableKey} dynamic>
            {children}
          </ClerkProvider>
        ) : (
          children
        )}
      </body>
    </html>
  );
}
