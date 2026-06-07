'use client';

import { SUPPORTED_LANGUAGES } from '@/types';
import { ArrowLeftRight, ChevronDown } from 'lucide-react';

interface LanguageSelectorProps {
  sourceLang: string;
  targetLang: string;
  onSourceLangChange: (lang: string) => void;
  onTargetLangChange: (lang: string) => void;
  disabled?: boolean;
}

export function LanguageSelector({
  sourceLang,
  targetLang,
  onSourceLangChange,
  onTargetLangChange,
  disabled = false,
}: LanguageSelectorProps) {
  const swapLanguages = () => {
    if (disabled) {
      return;
    }
    onSourceLangChange(targetLang);
    onTargetLangChange(sourceLang);
  };

  const selectFields = [
    { value: sourceLang, onChange: onSourceLangChange, label: 'Source language' },
    { value: targetLang, onChange: onTargetLangChange, label: 'Target language' },
  ];

  return (
    <div className="flex flex-wrap items-center justify-center gap-3">
      {selectFields.map((field, index) => (
        <div key={field.label} className={index === 0 ? 'order-1' : 'order-3'}>
          <div className="relative">
            <select
              value={field.value}
              onChange={(event) => field.onChange(event.target.value)}
              disabled={disabled}
              className={`h-10 min-w-[90px] appearance-none rounded-lg border border-slate-200 bg-white pl-3 pr-8 py-1.5 text-[13px] font-medium text-slate-700 outline-none transition-colors ${
                disabled ? 'cursor-not-allowed opacity-60' : 'hover:border-slate-300'
              }`}
              aria-label={field.label}
            >
              {SUPPORTED_LANGUAGES.map((lang) => (
                <option key={lang.code} value={lang.code}>
                  {lang.name}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-slate-400" strokeWidth={2} />
          </div>
        </div>
      ))}

      <button
        type="button"
        onClick={swapLanguages}
        disabled={disabled}
        className="order-2 inline-flex h-10 w-10 items-center justify-center rounded-lg border border-transparent bg-transparent text-slate-500 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
        aria-label="Swap languages"
      >
        <ArrowLeftRight className="size-4" strokeWidth={2} />
      </button>
    </div>
  );
}
