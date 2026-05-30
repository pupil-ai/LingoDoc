'use client';

import { motion } from 'framer-motion';
import { SUPPORTED_LANGUAGES } from '@/types';

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
    if (disabled) return;
    onSourceLangChange(targetLang);
    onTargetLangChange(sourceLang);
  };

  return (
    <motion.div
      className="flex items-center justify-center gap-4 flex-wrap"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
    >
      <div className="flex-1 min-w-[200px]">
        <label className="block text-sm font-medium text-gray-600 mb-2">
          Source Language
        </label>
        <select
          value={sourceLang}
          onChange={(e) => onSourceLangChange(e.target.value)}
          disabled={disabled}
          className={`
            w-full px-4 py-3 rounded-xl border transition-all duration-200
            ${disabled
              ? 'bg-gray-100 border-gray-200 text-gray-400 cursor-not-allowed'
              : 'bg-white border-gray-200 hover:border-primary-400 focus:border-primary-500 focus:ring-2 focus:ring-primary-100'
            }
          `}
        >
          {SUPPORTED_LANGUAGES.map((lang) => (
            <option key={lang.code} value={lang.code}>
              {lang.name}
            </option>
          ))}
        </select>
      </div>

      <motion.button
        onClick={swapLanguages}
        disabled={disabled}
        className={`
          mt-7 p-3 rounded-full transition-all duration-200
          ${disabled
            ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
            : 'bg-primary-100 text-primary-600 hover:bg-primary-200 hover:scale-110'
          }
        `}
        whileHover={!disabled ? { scale: 1.1 } : {}}
        whileTap={!disabled ? { scale: 0.9 } : {}}
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
        </svg>
      </motion.button>

      <div className="flex-1 min-w-[200px]">
        <label className="block text-sm font-medium text-gray-600 mb-2">
          Target Language
        </label>
        <select
          value={targetLang}
          onChange={(e) => onTargetLangChange(e.target.value)}
          disabled={disabled}
          className={`
            w-full px-4 py-3 rounded-xl border transition-all duration-200
            ${disabled
              ? 'bg-gray-100 border-gray-200 text-gray-400 cursor-not-allowed'
              : 'bg-white border-gray-200 hover:border-primary-400 focus:border-primary-500 focus:ring-2 focus:ring-primary-100'
            }
          `}
        >
          {SUPPORTED_LANGUAGES.map((lang) => (
            <option key={lang.code} value={lang.code}>
              {lang.name}
            </option>
          ))}
        </select>
      </div>
    </motion.div>
  );
}
