'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { Header } from '@/components/Header';

const plans = [
  {
    name: 'Free',
    price: '$0',
    description: 'Try LingoDoc before upgrading.',
    badge: 'Current default',
    quota: '30 preview pages / month',
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
    name: 'Starter',
    price: 'Coming soon',
    description: 'For short PDFs and occasional full translations.',
    badge: 'Entry paid',
    quota: '500 pages / month',
    limits: ['Up to 50 pages per PDF', 'PDF up to 50 MB'],
    features: [
      'Full-document translation for small files',
      'Full bilingual PDF export',
      'Translated-only PDF export',
      'File history and private workspace',
    ],
    button: 'Paddle checkout coming soon',
    href: '#',
    highlighted: false,
  },
  {
    name: 'Pro',
    price: 'Coming soon',
    description: 'For regular documents, reports, and papers.',
    badge: 'Recommended',
    quota: '3,000 pages / month',
    limits: ['Up to 300 pages per PDF', 'PDF up to 100 MB'],
    features: [
      'Translate regular long-form PDFs',
      'Full bilingual PDF export',
      'Translated-only PDF export',
      'File history and private workspace',
    ],
    button: 'Paddle checkout coming soon',
    href: '#',
    highlighted: true,
  },
  {
    name: 'Power',
    price: 'Coming soon',
    description: 'For books, manuals, and very large files.',
    badge: 'Large files',
    quota: '30,000 pages / month',
    limits: ['Up to 3000 pages per PDF', 'PDF up to 250 MB'],
    features: [
      'Designed for long-form documents',
      'Translate books, manuals, and archives',
      'Priority large-file processing later',
      'Best fit for heavy translation needs',
    ],
    button: 'Paddle checkout coming soon',
    href: '#',
    highlighted: false,
  },
];

export default function PricingPage() {
  const [billingCycle, setBillingCycle] = useState<'monthly' | 'yearly'>('monthly');
  const isYearly = billingCycle === 'yearly';

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
            Paddle subscriptions are planned next
          </span>
          <h1 className="font-display mt-6 text-4xl md:text-5xl font-bold text-gray-900">
            Simple plans for PDF translation
          </h1>
          <p className="mt-4 text-lg text-gray-600 max-w-2xl mx-auto">
            Each plan includes a monthly translated-page quota plus a per-PDF page and file-size limit.
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
                <span className="text-3xl font-bold text-gray-900">{plan.price}</span>
                {plan.price !== '$0' && (
                  <span className="ml-2 text-sm text-gray-500">
                    {isYearly ? 'yearly via Paddle later' : 'monthly via Paddle later'}
                  </span>
                )}
                {isYearly && plan.price !== '$0' && (
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

              <a
                href={plan.href}
                className={`mt-8 block rounded-xl px-5 py-3 text-center text-sm font-semibold transition-colors ${
                  plan.href === '#'
                    ? 'cursor-not-allowed bg-gray-100 text-gray-500'
                    : 'gradient-primary text-white hover:opacity-90'
                }`}
                aria-disabled={plan.href === '#'}
              >
                {plan.button}
              </a>
            </motion.div>
          ))}
        </div>

        <div className="mt-10 rounded-2xl border border-amber-100 bg-amber-50/80 p-5 text-sm text-amber-800">
          Pricing amounts are not final yet. The page currently documents the planned Free, Starter, Pro, and Power limits before Paddle checkout is connected.
        </div>
      </main>
    </div>
  );
}
