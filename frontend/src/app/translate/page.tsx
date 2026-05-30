'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useSearchParams, useRouter } from 'next/navigation';
import { Header } from '@/components/Header';
import { ProgressBar } from '@/components/ProgressBar';
import { BilingualReader } from '@/components/BilingualReader';
import { LanguageSelector } from '@/components/LanguageSelector';
import { startTranslation, getTranslationProgress, getTranslationResult } from '@/lib/api';
import type { TranslationProgress, TranslationResult } from '@/types';

export default function TranslatePage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  
  const fileId = searchParams.get('fileId');
  const initialSourceLang = searchParams.get('sourceLang') || 'en';
  const initialTargetLang = searchParams.get('targetLang') || 'zh';

  const [sourceLang, setSourceLang] = useState(initialSourceLang);
  const [targetLang, setTargetLang] = useState(initialTargetLang);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [progress, setProgress] = useState<TranslationProgress>({
    status: 'processing',
    progress: 0,
    processedPages: 0,
    totalPages: 0,
  });
  const [result, setResult] = useState<TranslationResult | null>(null);
  const [isTranslating, setIsTranslating] = useState(false);
  const [error, setError] = useState('');

  const startTranslate = async () => {
    if (!fileId) return;
    
    setIsTranslating(true);
    setError('');
    
    try {
      const response = await startTranslation({
        fileId,
        sourceLang,
        targetLang,
      });
      
      if (response.success) {
        setTaskId(response.taskId);
      } else {
        setError('Failed to start translation');
      }
    } catch (err) {
      setError('An error occurred. Please try again.');
    } finally {
      setIsTranslating(false);
    }
  };

  const pollProgress = useCallback(async () => {
    if (!taskId) return;

    try {
      const progressData = await getTranslationProgress(taskId);
      setProgress(progressData);

      if (progressData.status === 'completed') {
        const resultData = await getTranslationResult(taskId);
        setResult(resultData);
      } else if (progressData.status === 'processing') {
        setTimeout(pollProgress, 2000);
      }
    } catch (err) {
      setError('Failed to get translation progress');
    }
  }, [taskId]);

  useEffect(() => {
    if (taskId && progress.status === 'processing') {
      pollProgress();
    }
  }, [taskId, pollProgress, progress.status]);

  useEffect(() => {
    if (!fileId) {
      router.push('/');
    }
  }, [fileId, router]);

  if (!fileId) {
    return null;
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-cyan-50">
      <Header />

      <section className="max-w-6xl mx-auto px-4 py-8">
        <motion.div
          className="mb-8"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <button
            onClick={() => router.push('/')}
            className="flex items-center gap-2 text-gray-600 hover:text-primary-600 mb-4 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            <span>Back to Home</span>
          </button>

          <h1 className="font-display text-3xl font-bold text-gray-900 mb-2">
            Translating PDF
          </h1>
          <p className="text-gray-600">File ID: {fileId}</p>
        </motion.div>

        <AnimatePresence mode="wait">
          {!result ? (
            <motion.div
              key="progress"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <div className="bg-white/70 backdrop-blur-sm rounded-3xl p-8 shadow-xl border border-white/50 mb-8">
                <LanguageSelector
                  sourceLang={sourceLang}
                  targetLang={targetLang}
                  onSourceLangChange={setSourceLang}
                  onTargetLangChange={setTargetLang}
                  disabled={isTranslating || !!taskId}
                />

                {!taskId && (
                  <motion.button
                    onClick={startTranslate}
                    disabled={isTranslating}
                    className="w-full mt-6 py-4 gradient-primary text-white font-semibold rounded-xl hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
                    whileHover={{ scale: 1.01 }}
                    whileTap={{ scale: 0.99 }}
                  >
                    {isTranslating ? 'Starting...' : 'Start Translation'}
                  </motion.button>
                )}
              </div>

              {taskId && <ProgressBar progress={progress} />}

              {error && (
                <motion.p
                  className="mt-4 text-center text-red-500"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                >
                  {error}
                </motion.p>
              )}
            </motion.div>
          ) : (
            <motion.div
              key="result"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <div className="bg-white/70 backdrop-blur-sm rounded-3xl p-8 shadow-xl border border-white/50 mb-8">
                <div className="flex items-center justify-between">
                  <h2 className="text-xl font-semibold text-gray-800">Translation Complete!</h2>
                  <button
                    onClick={() => router.push('/')}
                    className="px-6 py-2 gradient-primary text-white font-medium rounded-xl hover:opacity-90 transition-opacity"
                  >
                    Translate Another File
                  </button>
                </div>
              </div>

              <BilingualReader pages={result.pages} />
            </motion.div>
          )}
        </AnimatePresence>
      </section>
    </div>
  );
}
