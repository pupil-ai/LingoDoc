'use client';

import { useEffect, useRef, useState } from 'react';
import { SignInButton, useAuth, useUser } from '@clerk/nextjs';
import { Check, Mail, Sparkles, X } from 'lucide-react';
import { Header } from '@/components/Header';

declare global {
  interface Window {
    Paddle?: {
      Environment?: {
        set: (environment: string) => void;
      };
      Initialize: (options: { token: string }) => void;
      PricePreview?: (request: {
        items: { priceId: string; quantity: number }[];
      }) => Promise<{
        data?: {
          details?: {
            lineItems?: Array<{
              formattedTotals?: { subtotal?: string };
              price?: {
                id?: string;
                unitPrice?: {
                  amount?: string;
                  currencyCode?: string;
                };
              };
            }>;
          };
        };
      }>;
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
    subtitle: 'Guest mode',
    monthlyPrice: 0,
    yearlyPrice: 0,
    monthlyPriceId: '',
    yearlyPriceId: '',
    button: 'Get Started Free',
    items: ['20 pages / month', 'Preview first 3 pages', 'PDF up to 25 MB'],
    highlighted: false,
    badge: '',
  },
  {
    key: 'starter',
    name: 'Starter',
    subtitle: 'For casual users',
    monthlyPrice: 15,
    yearlyPrice: 144,
    monthlyPriceId: process.env.NEXT_PUBLIC_PADDLE_STARTER_MONTHLY_PRICE_ID || '',
    yearlyPriceId: process.env.NEXT_PUBLIC_PADDLE_STARTER_YEARLY_PRICE_ID || '',
    button: 'Choose Starter',
    items: ['100 pages / month', 'Up to 50 pages per PDF', 'PDF up to 50 MB', 'File history'],
    highlighted: false,
    badge: '',
  },
  {
    key: 'pro',
    name: 'Pro',
    subtitle: 'Recommended',
    monthlyPrice: 50,
    yearlyPrice: 480,
    monthlyPriceId: process.env.NEXT_PUBLIC_PADDLE_PRO_MONTHLY_PRICE_ID || '',
    yearlyPriceId: process.env.NEXT_PUBLIC_PADDLE_PRO_YEARLY_PRICE_ID || '',
    button: 'Choose Pro',
    items: ['500 pages / month', 'Up to 300 pages per PDF', 'PDF up to 100 MB', 'File history'],
    highlighted: true,
    badge: 'Most popular',
  },
  {
    key: 'power',
    name: 'Power',
    subtitle: 'Large scale',
    monthlyPrice: 250,
    yearlyPrice: 2400,
    monthlyPriceId: process.env.NEXT_PUBLIC_PADDLE_POWER_MONTHLY_PRICE_ID || '',
    yearlyPriceId: process.env.NEXT_PUBLIC_PADDLE_POWER_YEARLY_PRICE_ID || '',
    button: 'Choose Power',
    items: [
      '3,000 pages / month',
      'Up to 3000 pages per PDF',
      'PDF up to 250 MB',
      'File history',
      'Designed for long-form documents',
      'Priority large-file processing later',
      'Best fit for heavy translation needs',
    ],
    highlighted: false,
    badge: '',
  },
];

function formatCurrency(value: number): string {
  return `$${value.toLocaleString('en-US')}`;
}

function formatMonthlyEquivalent(yearlyPrice: number): string {
  if (yearlyPrice === 0) {
    return '$0';
  }

  return formatCurrency(Math.round(yearlyPrice / 12));
}

function formatCurrencyByCode(value: number, currencyCode = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currencyCode,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

type PricingPreviewMap = Partial<Record<(typeof plans)[number]['key'], {
  monthlyLabel: string;
  yearlyMonthlyLabel: string;
  yearlyBilledLabel: string;
}>>;

const faqs = [
  {
    title: 'Can I change my plan later?',
    body: 'Yes, you can upgrade or downgrade at any time. Changes take effect immediately and we will prorate the difference.',
  },
  {
    title: 'What payment methods do you accept?',
    body: 'We accept all major credit cards (Visa, MasterCard, American Express) and PayPal.',
  },
  {
    title: 'Is there a free trial?',
    body: 'Yes. The Free plan requires no credit card. To prevent abuse, translations are limited to the first 3 pages per document.',
  },
  {
    title: 'What download formats are available?',
    body: 'You can download bilingual PDFs (side-by-side view) or translation-only PDFs. Both preserve the original layout and formatting.',
  },
];

function ClerkSetupRequired() {
  return (
    <div className="app-shell">
      <Header />
      <section className="page-container py-24">
        <div className="mx-auto max-w-[560px] rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-[var(--shadow-card)]">
          <h1 className="text-[40px] font-bold tracking-[-0.05em] text-slate-900">Clerk setup required</h1>
          <p className="mt-4 text-[16px] leading-relaxed text-slate-600">
            Add your Clerk publishable key to <span className="font-semibold">frontend/.env.local</span> before testing plan flows.
          </p>
        </div>
      </section>
    </div>
  );
}

function ContactModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) {
    return null;
  }

  return (
    <div className="overlay-scrim fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-2xl bg-white p-8 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100"
            aria-label="Close contact modal"
          >
            <X className="size-4" strokeWidth={2} />
          </button>
        </div>

        <div className="mx-auto mt-[-4px] flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-slate-700 to-slate-900 text-white shadow-lg">
          <Mail className="size-8" strokeWidth={2} />
        </div>

        <h3 className="mt-5 text-center text-[28px] font-bold tracking-[-0.04em] text-slate-900">Contact Us</h3>
        <p className="mt-2 text-center text-[16px] text-slate-500">Get in touch with our team for custom solutions</p>

        <div className="mt-8 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-center gap-4">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-400">
              <Mail className="size-5" strokeWidth={2} />
            </div>
            <div>
              <p className="text-[12px] font-medium text-slate-400">Email</p>
              <p className="mt-1 text-[16px] font-medium text-slate-700">support@lingodoc.com</p>
            </div>
          </div>
        </div>

        <p className="mt-6 text-center text-[13px] text-slate-400">We typically respond within 24 hours</p>
      </div>
    </div>
  );
}

function PlanCard({
  plan,
  isYearly,
  isLoaded,
  isSignedIn,
  checkoutPlan,
  previewPrice,
  onSelect,
}: {
  plan: (typeof plans)[number];
  isYearly: boolean;
  isLoaded: boolean;
  isSignedIn: boolean;
  checkoutPlan: string;
  previewPrice?: PricingPreviewMap[(typeof plans)[number]['key']];
  onSelect: (plan: (typeof plans)[number]) => void;
}) {
  const displayPrice = isYearly
    ? (previewPrice?.yearlyMonthlyLabel ?? formatMonthlyEquivalent(plan.yearlyPrice))
    : (previewPrice?.monthlyLabel ?? formatCurrency(plan.monthlyPrice));
  const billedYearlyLabel = previewPrice?.yearlyBilledLabel ?? `Billed ${formatCurrency(plan.yearlyPrice)}/year`;

  return (
    <div
      className={`relative rounded-2xl border bg-white p-6 transition-all hover:-translate-y-0.5 hover:shadow-md ${
        plan.highlighted ? 'border-emerald-500 shadow-lg shadow-emerald-500/10' : 'border-slate-200'
      }`}
    >
      {plan.badge && (
        <span className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-600 px-3 py-1 text-[11px] font-semibold text-white">
          {plan.badge}
        </span>
      )}

      <h2 className="text-[17px] font-bold text-slate-900">{plan.name}</h2>
      <p className="mt-1 text-[13px] text-slate-500">{plan.subtitle}</p>

      <div className="mt-5 flex items-end gap-1">
        <span className="text-[56px] font-bold leading-none tracking-[-0.05em] text-slate-900">
          {displayPrice}
        </span>
        {plan.key !== 'free' && <span className="pb-1 text-[14px] text-slate-500">/month</span>}
      </div>

      {plan.key !== 'free' && isYearly && (
        <p className="mt-2 text-[13px] font-semibold text-emerald-600">
          {billedYearlyLabel}
        </p>
      )}

      {plan.key !== 'free' && isLoaded && !isSignedIn ? (
        <SignInButton mode="modal">
          <button className={`mt-6 w-full rounded-lg px-4 py-2 text-[13px] font-semibold text-white transition-all ${
            plan.highlighted ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-slate-900 hover:bg-slate-800'
          }`}>
            Sign in to choose
          </button>
        </SignInButton>
      ) : (
        <button
          type="button"
          onClick={() => onSelect(plan)}
          disabled={checkoutPlan === plan.key}
          className={`mt-6 w-full rounded-lg px-4 py-2 text-[13px] font-semibold text-white transition-all disabled:cursor-wait disabled:opacity-70 ${
            plan.highlighted ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-slate-900 hover:bg-slate-800'
          }`}
        >
          {checkoutPlan === plan.key ? 'Opening checkout...' : plan.button}
        </button>
      )}

      <ul className="mt-6 space-y-3">
        {plan.items.map((item) => (
          <li key={item} className="flex items-start gap-3 text-[14px] leading-6 text-slate-600">
            <Check className="mt-0.5 size-4 shrink-0 text-emerald-600" strokeWidth={2} />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PricingPageContent() {
  const [billingCycle, setBillingCycle] = useState<'monthly' | 'yearly'>('monthly');
  const [checkoutStatus, setCheckoutStatus] = useState('');
  const [checkoutPlan, setCheckoutPlan] = useState('');
  const [isContactOpen, setIsContactOpen] = useState(false);
  const [previewPrices, setPreviewPrices] = useState<PricingPreviewMap>({});
  const paddleInitializedRef = useRef(false);
  const { isLoaded, isSignedIn } = useAuth();
  const { user } = useUser();
  const isYearly = billingCycle === 'yearly';

  const initializePaddle = async () => {
    await loadPaddleScript();

    if (!window.Paddle) {
      throw new Error('Paddle.js did not initialize.');
    }

    if (!paddleInitializedRef.current) {
      window.Paddle.Environment?.set(PADDLE_ENVIRONMENT);
      window.Paddle.Initialize({ token: PADDLE_CLIENT_TOKEN });
      paddleInitializedRef.current = true;
    }

    return window.Paddle;
  };

  useEffect(() => {
    async function loadPreviewPrices() {
      if (!PADDLE_CLIENT_TOKEN) {
        return;
      }

      const paidPlans = plans.filter((plan) => plan.key !== 'free');

      try {
        const paddle = await initializePaddle();
        if (!paddle.PricePreview) {
          return;
        }

        const monthlyPreview = await paddle.PricePreview({
          items: paidPlans.map((plan) => ({
            priceId: plan.monthlyPriceId,
            quantity: 1,
          })),
        });

        const yearlyPreview = await paddle.PricePreview({
          items: paidPlans.map((plan) => ({
            priceId: plan.yearlyPriceId,
            quantity: 1,
          })),
        });

        const monthlyLineItems = monthlyPreview.data?.details?.lineItems ?? [];
        const yearlyLineItems = yearlyPreview.data?.details?.lineItems ?? [];

        const monthlyByPriceId = new Map(
          monthlyLineItems.map((item) => [item.price?.id, item])
        );
        const yearlyByPriceId = new Map(
          yearlyLineItems.map((item) => [item.price?.id, item])
        );

        const nextPreviewPrices: PricingPreviewMap = {};

        for (const plan of paidPlans) {
          const monthlyItem = monthlyByPriceId.get(plan.monthlyPriceId);
          const yearlyItem = yearlyByPriceId.get(plan.yearlyPriceId);

          const monthlyAmountMinor = Number(monthlyItem?.price?.unitPrice?.amount ?? 0);
          const monthlyCurrencyCode = monthlyItem?.price?.unitPrice?.currencyCode ?? 'USD';
          const monthlyAmountMajor = monthlyAmountMinor / 100;
          const yearlyAmountMinor = Number(yearlyItem?.price?.unitPrice?.amount ?? 0);
          const yearlyCurrencyCode = yearlyItem?.price?.unitPrice?.currencyCode ?? 'USD';
          const yearlyAmountMajor = yearlyAmountMinor / 100;

          nextPreviewPrices[plan.key] = {
            monthlyLabel: monthlyAmountMajor > 0
              ? formatCurrencyByCode(Math.round(monthlyAmountMajor), monthlyCurrencyCode)
              : formatCurrency(plan.monthlyPrice),
            yearlyMonthlyLabel: yearlyAmountMajor > 0
              ? formatCurrencyByCode(Math.round(yearlyAmountMajor / 12), yearlyCurrencyCode)
              : formatMonthlyEquivalent(plan.yearlyPrice),
            yearlyBilledLabel: yearlyAmountMajor > 0
              ? `Billed ${formatCurrencyByCode(Math.round(yearlyAmountMajor), yearlyCurrencyCode)}/year`
              : `Billed ${formatCurrency(plan.yearlyPrice)}/year`,
          };
        }

        setPreviewPrices(nextPreviewPrices);
      } catch (error) {
        console.error('Failed to load Paddle preview prices:', error);
      }
    }

    loadPreviewPrices();
  }, []);

  const handleCheckout = async (plan: (typeof plans)[number]) => {
    if (plan.key === 'free') {
      window.location.href = '/';
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
      const paddle = await initializePaddle();

      const email = user.primaryEmailAddress?.emailAddress;
      paddle.Checkout.open({
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
    <div className="app-shell">
      <Header />

      <main className="page-container pb-16 pt-10 sm:pb-24 sm:pt-14">
        <section className="text-center">
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1 text-[12px] font-semibold text-emerald-600">
            <Sparkles className="size-3" strokeWidth={2} />
            Simple, transparent pricing
          </span>

          <h1 className="mt-5 text-[48px] font-bold tracking-[-0.06em] text-slate-900">Choose your plan</h1>
          <p className="mx-auto mt-4 max-w-[620px] text-[17px] leading-relaxed text-slate-600">
            Start free, upgrade when you need more. All plans include bilingual PDF output and layout preservation.
          </p>

          <div className="mt-8 inline-flex rounded-xl bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => setBillingCycle('monthly')}
              className={`rounded-lg px-4 py-1.5 text-[13px] font-semibold ${
                billingCycle === 'monthly' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'
              }`}
            >
              Monthly
            </button>
            <button
              type="button"
              onClick={() => setBillingCycle('yearly')}
              className={`rounded-lg px-4 py-1.5 text-[13px] font-semibold ${
                billingCycle === 'yearly' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'
              }`}
            >
              Yearly <span className="text-emerald-600">-20%</span>
            </button>
          </div>

          {checkoutStatus && (
            <p className="mx-auto mt-6 max-w-[720px] rounded-xl border border-slate-200 bg-white px-4 py-3 text-[13px] font-medium text-slate-600">
              {checkoutStatus}
            </p>
          )}
        </section>

        <section className="mt-12 grid gap-4 xl:grid-cols-4">
          {plans.map((plan) => (
            <PlanCard
              key={plan.key}
              plan={plan}
              isYearly={isYearly}
              isLoaded={isLoaded}
              isSignedIn={Boolean(isSignedIn)}
              checkoutPlan={checkoutPlan}
              previewPrice={previewPrices[plan.key]}
              onSelect={handleCheckout}
            />
          ))}
        </section>

        <section className="mx-auto mt-20 max-w-[840px]">
          <h2 className="text-center text-[28px] font-bold tracking-[-0.04em] text-slate-900">Frequently asked questions</h2>
          <div className="mt-10 space-y-8">
            {faqs.map((item) => (
              <div key={item.title} className="border-b border-slate-100 pb-8">
                <h3 className="text-[20px] font-semibold tracking-[-0.02em] text-slate-900">{item.title}</h3>
                <p className="mt-3 text-[16px] leading-7 text-slate-600">{item.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mx-auto mt-20 max-w-[980px] rounded-2xl border border-slate-200 bg-slate-50 px-8 py-12 text-center">
          <h2 className="text-[28px] font-bold tracking-[-0.04em] text-slate-900">Need a custom solution?</h2>
          <p className="mx-auto mt-3 max-w-[540px] text-[16px] leading-relaxed text-slate-600">
            We offer custom plans for users with specific requirements.
          </p>
          <button
            type="button"
            onClick={() => setIsContactOpen(true)}
            className="mt-7 rounded-lg bg-slate-900 px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-slate-800"
          >
            Contact our sales team
          </button>
        </section>
      </main>

      <ContactModal open={isContactOpen} onClose={() => setIsContactOpen(false)} />
    </div>
  );
}

export default function PricingPage() {
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return <ClerkSetupRequired />;
  }

  return <PricingPageContent />;
}
