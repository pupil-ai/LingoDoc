'use client';

import type { TranslationProgress } from '@/types';

interface ProgressBarProps {
  progress: TranslationProgress;
}

export function ProgressBar({ progress }: ProgressBarProps) {
  const percentage = Math.max(0, Math.min(100, progress.progress || 0));
  const processedPages = Math.max(progress.translatedPages ?? 0, progress.processedPages ?? 0);
  const totalPages = progress.requestedPages ?? progress.totalPages ?? 0;

  return (
    <div className="w-full max-w-[420px]">
      <div className="mb-3 flex items-center justify-between text-[14px] text-slate-500">
        <span>
          Progress: {processedPages} / {totalPages} pages
        </span>
        <span className="font-semibold text-emerald-600">{Math.round(percentage)}%</span>
      </div>
      <div className="h-2 rounded-full bg-slate-200">
        <div
          className="h-2 rounded-full bg-gradient-to-r from-emerald-600 to-emerald-500 transition-[width] duration-300"
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}
