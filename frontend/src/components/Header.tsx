'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { SignInButton, UserButton, useAuth } from '@clerk/nextjs';
import { usePathname } from 'next/navigation';
import { Sparkles } from 'lucide-react';

function BrandMark() {
  return (
    <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-900 text-emerald-400">
      <Sparkles className="size-4" strokeWidth={2} />
    </div>
  );
}

function HeaderAuthActions() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [hasValidSession, setHasValidSession] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function checkSession() {
      if (!isLoaded || !isSignedIn) {
        setHasValidSession(false);
        return;
      }

      try {
        const token = await getToken({ skipCache: true });
        if (!cancelled) {
          setHasValidSession(Boolean(token));
        }
      } catch {
        if (!cancelled) {
          setHasValidSession(false);
        }
      }
    }

    checkSession();

    return () => {
      cancelled = true;
    };
  }, [getToken, isLoaded, isSignedIn]);

  if (hasValidSession) {
    return <UserButton />;
  }

  return (
    <SignInButton mode="modal">
      <button className="inline-flex items-center rounded-lg bg-slate-900 px-4 py-2 text-[13px] font-semibold text-white transition-all hover:bg-slate-800">
        Sign In
      </button>
    </SignInButton>
  );
}

export function Header() {
  const isClerkConfigured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);
  const pathname = usePathname();

  const links = [
    { href: '/dashboard', label: 'My Files' },
    { href: '/pricing', label: 'Pricing' },
  ];

  return (
    <header className="border-b border-[var(--color-line)] bg-white/95 backdrop-blur-sm">
      <div className="page-container flex h-14 items-center justify-between">
        <Link href="/" className="flex items-center gap-2.5">
          <BrandMark />
          <span className="text-[20px] font-bold tracking-[-0.02em] text-slate-900">LingoDoc</span>
        </Link>

        <div className="flex items-center gap-3">
          <nav className="hidden items-center gap-1 sm:flex">
            {links.map((link) => {
              const active = pathname === link.href;
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
                    active ? 'bg-slate-100 text-slate-900' : 'text-slate-500 hover:text-slate-900'
                  }`}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>

          {isClerkConfigured ? (
            <HeaderAuthActions />
          ) : (
            <span className="rounded-md bg-orange-50 px-2 py-1 text-[11px] font-medium text-orange-700">
              Clerk not configured
            </span>
          )}
        </div>
      </div>
    </header>
  );
}
