'use client';

import type { UsageResponse } from '@/types';

interface UsageSummaryCardProps {
  usage: UsageResponse | null;
  isLoading?: boolean;
  compact?: boolean;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('en').format(value);
}

function formatPlan(plan: string): string {
  return plan.charAt(0).toUpperCase() + plan.slice(1);
}

export function UsageSummaryCard({ usage, isLoading = false, compact = false }: UsageSummaryCardProps) {
  if (isLoading) {
    return (
      <div className="rounded-2xl border border-white/70 bg-white/70 p-5 shadow-sm">
        <div className="h-4 w-32 rounded-full bg-gray-100 animate-pulse" />
        <div className="mt-4 h-3 rounded-full bg-gray-100 animate-pulse" />
      </div>
    );
  }

  if (!usage) {
    return null;
  }

  const quota = usage.monthlyPageQuota;
  const usedPages = usage.usedPages;
  const remainingPages = usage.remainingPages;
  const percentage = quota > 0 ? Math.min((usedPages / quota) * 100, 100) : 0;
  const isOutOfQuota = remainingPages !== null && remainingPages <= 0;
  const isFreePlan = usage.plan === 'free';
  const planName = formatPlan(usage.plan);
  const statusBadgeClass = isFreePlan
    ? 'bg-slate-100 text-slate-700'
    : isOutOfQuota
      ? 'bg-amber-100 text-amber-700'
      : 'bg-emerald-100 text-emerald-700';
  const statusLabel = isFreePlan
    ? 'Preview only'
    : isOutOfQuota
      ? 'Quota reached'
      : 'Active';
  const summaryLabel = isFreePlan
    ? 'Current plan'
    : quota > 0
      ? 'Monthly allowance'
      : 'Usage';
  const limitLabel = isFreePlan
    ? `Preview limit: first ${usage.freePreviewPages} pages / ${usage.maxFileSizeMB} MB`
    : `PDF limit: ${usage.maxPagesPerFile} pages / ${usage.maxFileSizeMB} MB`;

  return (
    <div className={`rounded-2xl border p-5 shadow-sm ${
      isOutOfQuota
        ? 'border-amber-200 bg-amber-50/90'
        : 'border-white/70 bg-white/80'
    }`}>
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-primary-50 px-2.5 py-1 text-xs font-semibold uppercase tracking-wide text-primary-700">
              {summaryLabel}
            </span>
            <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${statusBadgeClass}`}>
              {statusLabel}
            </span>
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
              {usage.usageMonth}
            </span>
          </div>

          <div className="mt-3 flex flex-wrap items-end gap-x-3 gap-y-1">
            <p className="text-2xl font-bold text-gray-900">{planName}</p>
            {quota > 0 && (
              <p className="text-sm font-medium text-gray-500">
                {formatNumber(usedPages)} used of {formatNumber(quota)} pages
              </p>
            )}
          </div>

          <p className="mt-2 text-sm text-gray-600">
            {isFreePlan
              ? `${formatNumber(remainingPages || 0)} preview pages remaining this month. Each PDF translates up to the first ${usage.freePreviewPages} page${usage.freePreviewPages === 1 ? '' : 's'}.`
              : quota > 0
                ? `${formatNumber(remainingPages || 0)} pages remaining this month. Usage resets monthly.`
                : `${formatNumber(usedPages)} pages used this month.`}
          </p>
        </div>

        <div className="text-left md:text-right">
          <p className={`text-lg font-bold ${isOutOfQuota ? 'text-amber-700' : 'text-gray-900'}`}>
            {isFreePlan
              ? 'Preview mode'
              : remainingPages === null
                ? 'Unlimited'
                : `${formatNumber(remainingPages)} left`}
          </p>
          <p className="text-xs text-gray-500">
            {limitLabel}
          </p>
        </div>
      </div>

      {quota > 0 && (
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-gray-100">
          <div
            className={`h-full rounded-full ${isOutOfQuota ? 'bg-amber-500' : 'gradient-primary'}`}
            style={{ width: `${percentage}%` }}
          />
        </div>
      )}

      {!compact && (
        <div className="mt-4 flex flex-col gap-3 text-sm md:flex-row md:items-center md:justify-between">
          <p className={isOutOfQuota ? 'text-amber-700' : 'text-gray-500'}>
            {isOutOfQuota
              ? 'You have used your monthly quota. Upgrade to continue translating.'
              : isFreePlan
                ? `Each PDF translates up to the first ${usage.freePreviewPages} preview pages. Upgrade for full-document translation.`
                : 'Usage resets monthly. Larger plans unlock more pages and bigger files.'}
          </p>
          <a
            href="/pricing"
            className="font-semibold text-primary-600 hover:text-primary-700"
          >
            View plans
          </a>
        </div>
      )}
    </div>
  );
}
