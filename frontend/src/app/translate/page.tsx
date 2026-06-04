'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { SignInButton, useAuth } from '@clerk/nextjs';
import { useSearchParams, useRouter } from 'next/navigation';
import { Header } from '@/components/Header';
import { ProgressBar } from '@/components/ProgressBar';
import { BilingualReader } from '@/components/BilingualReader';
import { LanguageSelector } from '@/components/LanguageSelector';
import { startTranslation, getTranslationProgress, getTranslationResult, getMyUsage } from '@/lib/api';
import type { TranslationProgress, TranslationResult, UsageResponse } from '@/types';

function ClerkSetupRequired() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-cyan-50">
      <Header />
      <section className="max-w-xl mx-auto px-4 py-24">
        <div className="bg-white/80 backdrop-blur-sm rounded-3xl p-8 shadow-xl border border-white/50 text-center">
          <h1 className="font-display text-3xl font-bold text-gray-900 mb-3">
            Clerk setup required
          </h1>
          <p className="text-gray-600">
            Add your Clerk publishable key to <span className="font-mono">frontend/.env.local</span> before translating files.
          </p>
        </div>
      </section>
    </div>
  );
}

function shouldShowPricingLink(message: string): boolean {
  const normalized = message.toLowerCase();
  return (
    normalized.includes('plan') ||
    normalized.includes('quota') ||
    normalized.includes('remaining') ||
    normalized.includes('upgrade')
  );
}

function TranslatePageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { getToken, isLoaded, isSignedIn } = useAuth();
  
  const fileId = searchParams.get('fileId');
  const filename = searchParams.get('filename');
  const initialTotalPages = Number(searchParams.get('totalPages') || '0');
  const initialTaskId = searchParams.get('taskId');
  const initialSourceLang = searchParams.get('sourceLang') || 'en';
  const initialTargetLang = searchParams.get('targetLang') || 'zh';

  const [sourceLang, setSourceLang] = useState(initialSourceLang);
  const [targetLang, setTargetLang] = useState(initialTargetLang);
  const [taskId, setTaskId] = useState<string | null>(initialTaskId);
  const [progress, setProgress] = useState<TranslationProgress>({
    status: 'processing',
    progress: 0,
    processedPages: 0,
    totalPages: 0,
  });
  const [result, setResult] = useState<TranslationResult | null>(null);
  const [isTranslating, setIsTranslating] = useState(false);
  const [isPreparingPreview, setIsPreparingPreview] = useState(false);
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [isUsageLoading, setIsUsageLoading] = useState(false);
  const [error, setError] = useState('');
  const displayFileName = filename || fileId;
  const knownTotalPages = progress.totalPages || result?.totalPages || initialTotalPages || 0;
  const isFreePlan = usage?.plan === 'free';
  const freePreviewPages = Math.min(
    usage?.freePreviewPages || 3,
    knownTotalPages || usage?.freePreviewPages || 3
  );
  const exceedsPaidFileLimit = Boolean(
    usage &&
    !isFreePlan &&
    knownTotalPages > 0 &&
    usage.maxPagesPerFile > 0 &&
    knownTotalPages > usage.maxPagesPerFile
  );
  const exceedsPaidMonthlyQuota = Boolean(
    usage &&
    !isFreePlan &&
    knownTotalPages > 0 &&
    usage.remainingPages !== null &&
    knownTotalPages > usage.remainingPages
  );
  const isStartBlocked = exceedsPaidFileLimit || exceedsPaidMonthlyQuota;

  const loadUsage = useCallback(async () => {
    if (!isLoaded || !isSignedIn) {
      setUsage(null);
      return;
    }

    setIsUsageLoading(true);

    try {
      const token = await getToken({ skipCache: true });
      const response = await getMyUsage(token);
      setUsage(response.success ? response : null);
    } catch {
      setUsage(null);
    } finally {
      setIsUsageLoading(false);
    }
  }, [getToken, isLoaded, isSignedIn]);

  const startTranslate = async () => {
    if (!fileId) return;
    if (!isSignedIn) {
      setError('Please sign in before translating this file.');
      return;
    }

    if (isStartBlocked) {
      setError('This file exceeds your current plan limits. Please upgrade to continue.');
      return;
    }
    
    setIsTranslating(true);
    setError('');
    
    try {
      const token = await getToken({ skipCache: true });
      const response = await startTranslation({
        fileId,
        sourceLang,
        targetLang,
      }, token);
      
      if (response.success) {
        setTaskId(response.taskId);
      } else {
        setError('Failed to start translation');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred. Please try again.');
    } finally {
      setIsTranslating(false);
    }
  };

  const pollProgress = useCallback(async () => {
    if (!taskId) return;

    try {
      const token = await getToken({ skipCache: true });
      const progressData = await getTranslationProgress(taskId, token);
      setProgress(progressData);

      if (progressData.status === 'completed') {
        setIsPreparingPreview(true);
        const resultData = await getTranslationResult(taskId, token);
        setResult(resultData);
        setIsPreparingPreview(false);
      } else if (progressData.status === 'processing') {
        setTimeout(pollProgress, 2000);
      }
    } catch (err) {
      setIsPreparingPreview(false);
      setError(err instanceof Error ? err.message : 'Failed to get translation progress');
    }
  }, [getToken, taskId]);

  useEffect(() => {
    if (taskId && progress.status === 'processing') {
      pollProgress();
    }
  }, [taskId, pollProgress, progress.status]);

  useEffect(() => {
    loadUsage();
  }, [loadUsage]);

  useEffect(() => {
    async function loadExistingResult() {
      if (!initialTaskId || !isLoaded || !isSignedIn || result) {
        return;
      }

      setIsPreparingPreview(true);
      setError('');

      try {
        const token = await getToken({ skipCache: true });
        const progressData = await getTranslationProgress(initialTaskId, token);
        setProgress(progressData);

        if (progressData.status === 'completed') {
          const resultData = await getTranslationResult(initialTaskId, token);
          setResult(resultData);
        } else if (progressData.status === 'processing') {
          setTaskId(initialTaskId);
        } else {
          setError(progressData.error || 'Translation task failed');
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load translation result');
      } finally {
        setIsPreparingPreview(false);
      }
    }

    loadExistingResult();
  }, [getToken, initialTaskId, isLoaded, isSignedIn, result]);

  useEffect(() => {
    if (!fileId) {
      router.push('/');
    }
  }, [fileId, router]);

  if (!fileId) {
    return null;
  }

  if (isLoaded && !isSignedIn) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-cyan-50">
        <Header />
        <section className="max-w-xl mx-auto px-4 py-24">
          <div className="bg-white/80 backdrop-blur-sm rounded-3xl p-8 shadow-xl border border-white/50 text-center">
            <h1 className="font-display text-3xl font-bold text-gray-900 mb-3">
              Sign in required
            </h1>
            <p className="text-gray-600 mb-6">
              Please sign in to translate files and access your private results.
            </p>
            <SignInButton mode="modal">
              <button className="px-6 py-3 gradient-primary text-white font-semibold rounded-xl hover:opacity-90 transition-opacity">
                Sign in
              </button>
            </SignInButton>
          </div>
        </section>
      </div>
    );
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
            Translating File
          </h1>
          <p className="text-gray-600">
            File: <span className="font-medium text-gray-800 break-all">{displayFileName}</span>
          </p>
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
                  <>
                    <div className={`mt-6 rounded-2xl border p-5 ${
                      isStartBlocked
                        ? 'border-amber-200 bg-amber-50/90'
                        : 'border-primary-100 bg-primary-50/60'
                    }`}>
                      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                        <div>
                          <p className="text-sm font-semibold text-gray-900">
                            Translation check
                          </p>
                          <p className="mt-2 text-sm text-gray-600">
                            {isUsageLoading
                              ? 'Checking your current plan and page allowance...'
                              : isFreePlan
                                ? `Free plan will translate the first ${freePreviewPages} page${freePreviewPages === 1 ? '' : 's'} as a preview${knownTotalPages ? ` from this ${knownTotalPages}-page file` : ''}.`
                                : knownTotalPages
                                  ? `This translation will use ${knownTotalPages} page${knownTotalPages === 1 ? '' : 's'} from your ${usage?.plan || 'current'} plan.`
                                  : 'This file will be checked against your plan limits before translation starts.'}
                          </p>
                          {!isFreePlan && usage && usage.remainingPages !== null && (
                            <p className="mt-2 text-xs text-gray-500">
                              Remaining this month: {usage.remainingPages} / {usage.monthlyPageQuota} pages.
                            </p>
                          )}
                          {exceedsPaidFileLimit && usage && (
                            <p className="mt-2 text-sm font-medium text-amber-700">
                              Your plan supports up to {usage.maxPagesPerFile} pages per PDF.
                            </p>
                          )}
                          {exceedsPaidMonthlyQuota && usage && (
                            <p className="mt-2 text-sm font-medium text-amber-700">
                              You do not have enough remaining pages this month.
                            </p>
                          )}
                        </div>
                        {isStartBlocked && (
                          <a href="/pricing" className="text-sm font-semibold text-primary-600 hover:text-primary-700">
                            View plans
                          </a>
                        )}
                      </div>
                    </div>

                    <motion.button
                      onClick={startTranslate}
                      disabled={isTranslating || !isLoaded || !isSignedIn || isStartBlocked}
                      className="w-full mt-6 py-4 gradient-primary text-white font-semibold rounded-xl hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
                      whileHover={{ scale: 1.01 }}
                      whileTap={{ scale: 0.99 }}
                    >
                      {isTranslating ? 'Starting...' : isFreePlan ? 'Start Free Preview' : 'Start Translation'}
                    </motion.button>
                  </>
                )}
              </div>

              {taskId && <ProgressBar progress={progress} />}

              {taskId && isPreparingPreview && (
                <motion.div
                  className="mt-6 bg-white/80 backdrop-blur-sm rounded-2xl p-6 shadow-lg border border-white/60 text-center"
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                >
                  <div className="mx-auto mb-4 h-10 w-10 rounded-full border-4 border-primary-100 border-t-primary-500 animate-spin" />
                  <h3 className="text-lg font-semibold text-gray-800">Preparing File Preview</h3>
                  <p className="mt-2 text-sm text-gray-500">
                    Translation is complete. Generating the preview can take a few seconds for layout-heavy files.
                  </p>
                </motion.div>
              )}

              {error && (
                <motion.div
                  className="mt-4 text-center"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                >
                  <p className="text-red-500">{error}</p>
                  {shouldShowPricingLink(error) && (
                    <a href="/pricing" className="mt-2 inline-block text-sm font-semibold text-primary-600 hover:text-primary-700">
                      View plans and limits
                    </a>
                  )}
                </motion.div>
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
                  <div>
                    <h2 className="text-xl font-semibold text-gray-800">Translation Complete!</h2>
                    {result.isPartial && (
                      <p className="mt-2 text-sm text-amber-600">
                        You are on the Free plan, so only the first {result.translatedPages || result.pages.length} pages were translated as a preview. This file has {result.totalPages || result.pages.length} pages in total.
                      </p>
                    )}
                  </div>
                  <button
                    onClick={() => router.push('/')}
                    className="px-6 py-2 gradient-primary text-white font-medium rounded-xl hover:opacity-90 transition-opacity"
                  >
                    Translate Another File
                  </button>
                </div>
              </div>

              <BilingualReader taskId={taskId!} fileId={fileId!} />
            </motion.div>
          )}
        </AnimatePresence>
      </section>
    </div>
  );
}

export default function TranslatePage() {
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return <ClerkSetupRequired />;
  }

  return <TranslatePageContent />;
}
