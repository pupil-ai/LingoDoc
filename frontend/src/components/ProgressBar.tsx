'use client';

import { motion } from 'framer-motion';
import type { TranslationProgress } from '@/types';

interface ProgressBarProps {
  progress: TranslationProgress;
}

export function ProgressBar({ progress }: ProgressBarProps) {
  const { status, progress: percentage, processedPages, totalPages } = progress;

  return (
    <motion.div
      className="w-full max-w-2xl mx-auto"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <div className="bg-white rounded-2xl shadow-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800">
            {status === 'processing' ? 'Translating...' : status === 'completed' ? 'Completed!' : 'Error'}
          </h3>
          <span className="text-sm font-medium text-gray-600">
            {processedPages} / {totalPages} pages
          </span>
        </div>

        <div className="relative h-3 bg-gray-100 rounded-full overflow-hidden">
          <motion.div
            className={`h-full rounded-full transition-colors duration-300 ${
              status === 'completed' ? 'bg-gradient-to-r from-green-400 to-green-600' :
              status === 'error' ? 'bg-red-500' :
              'bg-gradient-to-r from-primary-500 to-cyan-500'
            }`}
            initial={{ width: 0 }}
            animate={{ width: `${percentage}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          />
          {status === 'processing' && (
            <motion.div
              className="absolute inset-y-0 left-0 w-1/4 bg-white/30"
              animate={{
                left: ['0%', '100%'],
              }}
              transition={{
                duration: 1.5,
                repeat: Infinity,
                ease: 'easeInOut',
              }}
            />
          )}
        </div>

        <div className="flex items-center justify-between mt-3">
          <span className="text-sm text-gray-500">
            {status === 'processing' ? 'Estimating time...' :
             status === 'completed' ? 'Translation finished!' : 'Something went wrong'}
          </span>
          <span className="text-sm font-bold text-primary-600">
            {percentage.toFixed(1)}%
          </span>
        </div>
      </div>
    </motion.div>
  );
}
