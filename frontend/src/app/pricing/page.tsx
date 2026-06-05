'use client';

import { useRef, useState } from 'react';
import { SignInButton, useAuth, useUser } from '@clerk/nextjs';
import { motion } from 'framer-motion';
import { Header } from '@/components/Header';

declare global {
  interface Window {
    Paddle?: {
      Environment?: {
        set: (environment: string) => void;
      };
      Initialize: (options: { token: string }) => void;
      Checkout: {
        open: (options: {
          items: { priceId: string; quantity: number }[];
          customer?: { email: string };
          customData?: Record<string, string>;
        }) => void;
      };
    };
  }
}

const PADDLE_CLIENT_TOKEN = process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN || '';
const PADDLE_ENVIRONMENT = process.env.NEXT_PUBLIC_PADDLE_ENVIRONMENT || 'sandbox';

function loadPaddleScript(): Promise<void> {
  if (typeof window === 'undefined') {
    return Promise.reject(new Error('Paddle checkout is only available in the browser.'));
  }

  if (window.Paddle) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    const existingScript = document.querySelector<HTMLScriptElement>('script[data-paddle-js]');
    if (existingScript) {
      existingScript.addEventListener('load', () => resolve(), { once: true });
      existingScript.addEventListener('error', () => reject(new Error('Failed to load Paddle.js')), { once: true });
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://cdn.paddle.com/paddle/v2/paddle.js';
    script.async = true;
    script.dataset.paddleJs = 'true';
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load Paddle.js'));
    document.head.appendChild(script);
  });
}

const plans = [
  {
    key: 'free',
    name: 'Free',
    monthlyPrice: '$0',
    yearlyPrice: '$0',
    monthlyPriceId: '',
    yearlyPriceId: '',
    description: 'Try LingoDoc before upgrading.',
    badge: 'Current default',
    quota: 'Unlimited preview use',
    limits: ['Preview first 3 pages', 'PDF up to 25 MB'],
    features: [
      'Upload larger-page PDFs for preview',
      'Bilingual PDF preview and export',
      'Original layout preservation',
      'PDF uploads only',
    ],
    button: 'Start free preview',
    href: '/',
    highlighted: false,
  },
  {
    key: 'starter',
    name: 'Starter',
    monthlyPrice: '$12',
    yearlyPrice: '$99',
    monthlyPriceId: process.env.NEXT_PUBLIC_PADDLE_STARTER_MONTHLY_PRICE_ID || '',
    yearlyPriceId: process.env.NEXT_PUBLIC_PADDLE_STARTER_YEARLY_PRICE_ID || '',
    description: 'For short PDFs and occasional full translations.',
    badge: 'Entry paid',
    quota: '100 pages / month',
    limits: ['Up to 50 pages per PDF', 'PDF up to 50 MB'],
    features: [
      'Full-document translation for small files',
      'Full bilingual PDF export',
      'Translated-only PDF export',
      'File history and private workspace',
    ],
    button: 'Choose Starter',
    href: '#',
    highlighted: false,
  },
  {
    key: 'pro',
    name: 'Pro',
    monthlyPrice: '$49',
    yearlyPrice: '$399',
    monthlyPriceId: process.env.NEXT_PUBLIC_PADDLE_PRO_MONTHLY_PRICE_ID || '',
    yearlyPriceId: process.env.NEXT_PUBLIC_PADDLE_PRO_YEARLY_PRICE_ID || '',
    description: 'For regular documents, reports, and papers.',
    badge: 'Recommended',
    quota: '500 pages / month',
    limits: ['Up to 300 pages per PDF', 'PDF up to 100 MB'],
    features: [
      'Translate regular long-form PDFs',
      'Full bilingual PDF export',
      'Translated-only PDF export',
      'File history and private workspace',
    ],
    button: 'Choose Pro',
    href: '#',
    highlighted: true,
  },
  {
    key: 'power',
    name: 'Power',
    monthlyPrice: '$249',
    yearlyPrice: '$1,999',
    monthlyPriceId: process.env.NEXT_PUBLIC_PADDLE_POWER_MONTHLY_PRICE_ID || '',
    yearlyPriceId: process.env.NEXT_PUBLIC_PADDLE_POWER_YEARLY_PRICE_ID || '',
    description: 'For books, manuals, and very large files.',
    badge: 'Large files',
    quota: '3,000 pages / month',
    limits: ['Up to 3000 pages per PDF', 'PDF up to 250 MB'],
    features: [
      'Designed for long-form documents',
      'Translate books, manuals, and archives',
      'Priority large-file processing later',
      'Best fit for heavy translation needs',
    ],
    button: 'Choose Power',
    href: '#',
    highlighted: false,
  },
];

export default function PricingPage() {
  const [billingCycle, setBillingCycle] = useState<'monthly' | 'yearly'>('monthly');
  const [checkoutStatus, setCheckoutStatus] = useState('');
  const [checkoutPlan, setCheckoutPlan] = useState('');
  const paddleInitializedRef = useRef(false);
  const { isLoaded, isSignedIn } = useAuth();
  const { user } = useUser();
  const isYearly = billingCycle === 'yearly';

  const handleCheckout = async (plan: (typeof plans)[number]) => {
    if (plan.key === 'free') {
      window.location.href = plan.href;
      return;
    }

    if (!isLoaded || !isSignedIn || !user) {
      setCheckoutStatus('Please sign in before choosing a paid plan.');
      return;
    }

    if (!PADDLE_CLIENT_TOKEN) {
      setCheckoutStatus('Paddle is not configured yet. Add NEXT_PUBLIC_PADDLE_CLIENT_TOKEN.');
      return;
    }

    const priceId = isYearly ? plan.yearlyPriceId : plan.monthlyPriceId;
    if (!priceId) {
      setCheckoutStatus(`Paddle price ID is missing for ${plan.name} ${billingCycle}.`);
      return;
    }

    try {
      setCheckoutPlan(plan.key);
      setCheckoutStatus('Opening Paddle checkout...');
      await loadPaddleScript();

      if (!window.Paddle) {
        throw new Error('Paddle.js did not initialize.');
      }

      if (!paddleInitializedRef.current) {
        if (PADDLE_ENVIRONMENT) {
          window.Paddle.Environment?.set(PADDLE_ENVIRONMENT);
        }
        window.Paddle.Initialize({ token: PADDLE_CLIENT_TOKEN });
        paddleInitializedRef.current = true;
      }

      const email = user.primaryEmailAddress?.emailAddress;
      window.Paddle.Checkout.open({
        items: [{ priceId, quantity: 1 }],
        ...(email ? { customer: { email } } : {}),
        customData: {
          userId: user.id,
          plan: plan.key,
          billingCycle,
        },
      });
      setCheckoutStatus('Complete payment in the Paddle window. Your plan updates after the webhook is received.');
    } catch (error) {
      setCheckoutStatus(error instanceof Error ? error.message : 'Failed to open Paddle checkout.');
    } finally {
      setCheckoutPlan('');
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-cyan-50">
      <Header />

      <main className="max-w-6xl mx-auto px-4 py-16">
        <motion.section
          className="text-center mb-12"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45 }}
        >
          <span className="inline-flex items-center rounded-full bg-primary-100 px-4 py-2 text-sm font-medium text-primary-700">
            Pricing based on GPT-5.4 translation costs
          </span>
          <h1 className="font-display mt-6 text-4xl md:text-5xl font-bold text-gray-900">
            Simple plans for PDF translation
          </h1>
          <p className="mt-4 text-lg text-gray-600 max-w-2xl mx-auto">
            Free previews are limited per file. Paid plans include monthly translated-page quotas plus per-PDF page and file-size limits.
          </p>

          <div className="mt-8 inline-flex rounded-2xl bg-white/80 p-1 shadow-lg ring-1 ring-gray-100">
            <button
              type="button"
              onClick={() => setBillingCycle('monthly')}
              className={`rounded-xl px-5 py-2 text-sm font-semibold transition-colors ${
                billingCycle === 'monthly'
                  ? 'gradient-primary text-white'
                  : 'text-gray-600 hover:text-primary-600'
              }`}
            >
              Monthly
            </button>
            <button
              type="button"
              onClick={() => setBillingCycle('yearly')}
              className={`rounded-xl px-5 py-2 text-sm font-semibold transition-colors ${
                billingCycle === 'yearly'
                  ? 'gradient-primary text-white'
                  : 'text-gray-600 hover:text-primary-600'
              }`}
            >
              Yearly · Save 30%
            </button>
          </div>

          {checkoutStatus && (
            <p className="mt-5 rounded-2xl bg-white/80 px-4 py-3 text-sm font-medium text-gray-700 shadow-sm ring-1 ring-gray-100">
              {checkoutStatus}
            </p>
          )}
        </motion.section>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
          {plans.map((plan, index) => (
            <motion.div
              key={plan.name}
              className={`relative rounded-3xl border p-7 shadow-xl ${
                plan.highlighted
                  ? 'border-primary-200 bg-white ring-2 ring-primary-100'
                  : 'border-white/60 bg-white/75 backdrop-blur-sm'
              }`}
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: index * 0.08 }}
            >
              <div className="flex items-center justify-between gap-3">
                <h2 className="font-display text-2xl font-bold text-gray-900">{plan.name}</h2>
                <span className={`rounded-full px-3 py-1 text-xs font-semibold ${
                  plan.highlighted ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600'
                }`}>
                  {plan.badge}
                </span>
              </div>

              <p className="mt-3 text-sm text-gray-500">{plan.description}</p>
              <div className="mt-6">
                <span className="text-3xl font-bold text-gray-900">
                  {isYearly ? plan.yearlyPrice : plan.monthlyPrice}
                </span>
                {plan.monthlyPrice !== '$0' && (
                  <span className="ml-2 text-sm text-gray-500">
                    {isYearly ? '/ year' : '/ month'}
                  </span>
                )}
                {isYearly && plan.monthlyPrice !== '$0' && (
                  <p className="mt-2 text-sm font-semibold text-green-600">
                    Annual billing saves 30% compared with monthly.
                  </p>
                )}
              </div>

              <div className="mt-6 rounded-2xl bg-slate-50 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Monthly quota</p>
                <p className="mt-3 text-sm font-semibold text-gray-900">{plan.quota}</p>
              </div>

              <div className="mt-3 rounded-2xl bg-slate-50 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Single PDF limit</p>
                <div className="mt-3 space-y-2">
                  {plan.limits.map((limit) => (
                    <p key={limit} className="text-sm font-semibold text-gray-900">{limit}</p>
                  ))}
                </div>
              </div>

              <ul className="mt-7 space-y-3">
                {plan.features.map((feature) => (
                  <li key={feature} className="flex gap-3 text-sm text-gray-700">
                    <svg className="mt-0.5 h-5 w-5 flex-none text-primary-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>

              {plan.key !== 'free' && isLoaded && !isSignedIn ? (
                <SignInButton mode="modal">
                  <button className="mt-8 block w-full rounded-xl px-5 py-3 text-center text-sm font-semibold gradient-primary text-white transition-opacity hover:opacity-90">
                    Sign in to choose {plan.name}
                  </button>
                </SignInButton>
              ) : (
                <button
                  type="button"
                  onClick={() => handleCheckout(plan)}
                  disabled={checkoutPlan === plan.key}
                  className={`mt-8 block w-full rounded-xl px-5 py-3 text-center text-sm font-semibold transition-colors ${
                    checkoutPlan === plan.key
                      ? 'cursor-wait bg-gray-100 text-gray-500'
                      : 'gradient-primary text-white hover:opacity-90'
                  }`}
                >
                  {checkoutPlan === plan.key ? 'Opening checkout...' : plan.button}
                </button>
              )}
            </motion.div>
          ))}
        </div>

        <div className="mt-10 rounded-2xl border border-amber-100 bg-amber-50/80 p-5 text-sm text-amber-800">
          Paddle checkout is connected as a first pass. Add Paddle client token, price IDs, and webhook secret before testing real subscription updates.
        </div>
      </main>
    </div>
  );
}




