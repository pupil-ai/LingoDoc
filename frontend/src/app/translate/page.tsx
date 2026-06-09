'use client';

import type { ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SignInButton, useAuth } from '@clerk/nextjs';
import { useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeftRight, CheckCircle2, Download, FileText, Info, Loader2, X } from 'lucide-react';
import { LanguageSelector } from '@/components/LanguageSelector';
import { ProgressBar } from '@/components/ProgressBar';
import {
  exportTranslation,
  fetchExportPdfBlob,
  getMyUsage,
  getOriginalFilePreviewBlob,
  getTranslationProgress,
  getTranslationResult,
  startTranslation,
} from '@/lib/api';
import type { TranslationProgress, TranslationResult, UsageResponse } from '@/types';

type DownloadType = 'bilingual' | 'translated';
type ToastState =
  | {
      type: 'loading' | 'success' | 'error';
      message: string;
    }
  | null;

function ClerkSetupRequired() {
  return (
    <div className="app-shell">
      <section className="page-container py-24">
        <div className="mx-auto max-w-[560px] rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-[var(--shadow-card)]">
          <h1 className="text-[40px] font-bold tracking-[-0.05em] text-slate-900">Clerk setup required</h1>
          <p className="mt-4 text-[16px] leading-relaxed text-slate-600">
            Add your Clerk publishable key to <span className="font-semibold">frontend/.env.local</span> before translating files.
          </p>
        </div>
      </section>
    </div>
  );
}

function formatPlanName(plan: string | undefined): string {
  if (!plan) {
    return 'Current';
  }

  return `${plan.charAt(0).toUpperCase()}${plan.slice(1)} Plan`;
}

function labelForLang(code: string): string {
  const labels: Record<string, string> = {
    en: 'English',
    zh: 'Chinese',
    ja: 'Japanese',
    ko: 'Korean',
    fr: 'French',
    de: 'German',
    es: 'Spanish',
    ru: 'Russian',
  };
  return labels[code] || code.toUpperCase();
}

function PreviewPlaceholder({
  title,
  description,
  originalPreviewUrl,
  processing = false,
  footer,
  error,
  overlay = false,
}: {
  title: string;
  description: string;
  originalPreviewUrl: string | null;
  processing?: boolean;
  footer?: ReactNode;
  error?: string;
  overlay?: boolean;
}) {
  const content = (
    <div className="relative flex h-full min-h-0 w-full overflow-hidden bg-white">
      {originalPreviewUrl ? (
        <div className="absolute inset-0 flex items-center justify-center px-12 py-6">
          <img
            src={originalPreviewUrl}
            alt="Original PDF first page preview"
            className="h-full max-h-full w-auto max-w-full object-contain opacity-70"
          />
        </div>
      ) : (
        <div className="absolute inset-0 bg-gradient-to-br from-slate-100 via-white to-slate-100" />
      )}

      <div className="absolute inset-0 bg-white/55 backdrop-blur-sm" />
      <div className="absolute inset-0 bg-gradient-to-b from-white/70 via-white/80 to-white/90" />

      <div className="relative z-10 flex h-full w-full items-center justify-center px-6 py-10">
        <div className="w-full max-w-[540px] px-10 py-12 text-center">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-emerald-100 text-emerald-600 shadow-sm">
            {processing ? <Loader2 className="size-8 animate-spin" strokeWidth={2} /> : <ArrowLeftRight className="size-8" strokeWidth={2} />}
          </div>
          <h1 className="mt-8 text-[32px] font-bold tracking-[-0.04em] text-slate-900">{title}</h1>
          <p className="mt-4 text-[16px] leading-relaxed text-slate-500">{description}</p>
          {footer ? <div className="mt-8">{footer}</div> : null}
          {error ? <p className="mt-6 text-[14px] font-medium text-red-600">{error}</p> : null}
        </div>
      </div>
    </div>
  );

  if (overlay) {
    return content;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-50">
      <div className="w-full min-h-0 flex-1">
        <div className="h-full w-full overflow-hidden">
          {content}
        </div>
      </div>
    </div>
  );
}

function DownloadModal({
  open,
  filename,
  onClose,
  onDownload,
}: {
  open: boolean;
  filename: string;
  onClose: () => void;
  onDownload: (type: DownloadType) => void;
}) {
  if (!open) {
    return null;
  }

  const cards: Array<{ type: DownloadType; title: string; description: string }> = [
    {
      type: 'bilingual',
      title: 'Bilingual PDF',
      description: 'Side-by-side original and translation. Perfect for comparison and learning.',
    },
    {
      type: 'translated',
      title: 'Translation only',
      description: 'Just the translated text with original layout preserved.',
    },
  ];

  return (
    <div className="overlay-scrim fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h3 className="text-[17px] font-semibold text-slate-900">Download translated PDF</h3>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100"
            aria-label="Close download modal"
          >
            <X className="size-4" strokeWidth={2} />
          </button>
        </div>

        <div className="space-y-4 p-5">
          {cards.map((card) => (
            <button
              key={card.type}
              type="button"
              onClick={() => onDownload(card.type)}
              className="flex w-full items-start gap-4 rounded-2xl border border-slate-200 bg-white p-4 text-left transition-all hover:border-slate-300 hover:bg-slate-50 disabled:opacity-70"
            >
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600">
                <FileText className="size-6" strokeWidth={2} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[17px] font-semibold text-slate-900">{card.title}</p>
                <p className="mt-1 text-[14px] leading-6 text-slate-500">{card.description}</p>
              </div>
              <Download className="mt-1 size-4 shrink-0 text-slate-300" strokeWidth={2} />
            </button>
          ))}

        </div>

        <div className="border-t border-slate-100 px-5 py-4 text-[12px] text-slate-400">File name: {filename}</div>
      </div>
    </div>
  );
}

function DownloadToast({
  toast,
}: {
  toast: ToastState;
}) {
  if (!toast) {
    return null;
  }

  const styles =
    toast.type === 'error'
      ? 'border-red-200 bg-red-50 text-red-700'
      : toast.type === 'success'
        ? 'border-green-200 bg-green-50 text-green-700'
        : 'border-slate-200 bg-white text-slate-700';

  return (
    <div className="pointer-events-none fixed bottom-14 left-1/2 z-50 -translate-x-1/2 px-4">
      <div className={`flex min-w-[260px] items-center gap-3 rounded-xl border px-4 py-3 text-[13px] font-medium shadow-xl ${styles}`}>
        {toast.type === 'loading' ? <Loader2 className="size-4 animate-spin" strokeWidth={2} /> : null}
        <span>{toast.message}</span>
      </div>
    </div>
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
  const initialTaskStatus = searchParams.get('status');
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
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [isUsageLoading, setIsUsageLoading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isPreparingPreview, setIsPreparingPreview] = useState(false);
  const [originalPreviewObjectUrl, setOriginalPreviewObjectUrl] = useState<string | null>(null);
  const [previewBlob, setPreviewBlob] = useState<Blob | null>(null);
  const [previewObjectUrl, setPreviewObjectUrl] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState('');
  const [previewVersion] = useState(() => Date.now().toString());
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [error, setError] = useState('');
  const [isDownloadOpen, setIsDownloadOpen] = useState(false);
  const [downloadingType, setDownloadingType] = useState<DownloadType | null>(null);
  const [downloadToast, setDownloadToast] = useState<ToastState>(null);
  const isCompletedHistoryEntry = initialTaskStatus === 'completed';
  const isProcessingHistoryEntry = initialTaskStatus === 'processing';
  const [isRestoringCompletedTask, setIsRestoringCompletedTask] = useState(Boolean(initialTaskId && isCompletedHistoryEntry));
  const restoredCompletedTaskIdRef = useRef<string | null>(null);
  const isPollingRef = useRef(false);
  const pollErrorCountRef = useRef(0);

  const displayFileName = filename || fileId || 'document.pdf';
  const knownTotalPages = progress.totalPages || result?.totalPages || initialTotalPages || 0;
  const isFreePlan = usage?.plan === 'free';
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
  const isProcessing = Boolean(taskId) && !result;
  const isRestoringCompletedResult = Boolean(initialTaskId && isCompletedHistoryEntry) && !result && (isRestoringCompletedTask || isPreparingPreview);
  const isStartingTranslation = isStarting || isProcessing || isPreparingPreview;
  const originalPreviewUrl = useMemo(() => originalPreviewObjectUrl, [originalPreviewObjectUrl]);
  const previewUrl = useMemo(
    () => (previewObjectUrl ? `${previewObjectUrl}#page=1&zoom=page-fit` : null),
    [previewObjectUrl]
  );
  const isPreviewReady = Boolean(result && previewUrl && !isPreparingPreview && !isPreviewLoading && !previewError);

  const statusSummary = useMemo(() => {
    if (!usage) {
      return isUsageLoading ? 'Checking plan...' : 'Plan unavailable';
    }

    if (usage.plan === 'free') {
      return `${formatPlanName(usage.plan)} | Preview: ${usage.freePreviewPages} pages`;
    }

    return `${formatPlanName(usage.plan)} | Document: ${knownTotalPages} pages | Remaining: ${usage.remainingPages ?? 'Unlimited'} pages`;
  }, [isUsageLoading, knownTotalPages, usage]);

  const statusSummaryParts = useMemo(() => statusSummary.split(' | '), [statusSummary]);
  const remainingPagesToneClass = isFreePlan
    ? 'font-medium text-slate-500'
    : isStartBlocked
      ? 'font-semibold text-orange-600'
      : 'font-semibold text-green-600';

  const mergeProgress = useCallback(
    (current: TranslationProgress, incoming: TranslationProgress): TranslationProgress => {
      const incomingProcessed = incoming.processedPages ?? 0;
      const incomingTranslated = incoming.translatedPages ?? 0;
      const currentProcessed = current.processedPages ?? 0;
      const currentTranslated = current.translatedPages ?? 0;
      const mergedProcessed = Math.max(currentProcessed, incomingProcessed, incomingTranslated);
      const mergedTranslated = Math.max(currentTranslated, incomingTranslated, incomingProcessed);

      return {
        ...current,
        ...incoming,
        progress: Math.max(current.progress ?? 0, incoming.progress ?? 0),
        processedPages: mergedProcessed,
        translatedPages: mergedTranslated,
      };
    },
    []
  );

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

  const loadPreview = useCallback(
    async (activeTaskId: string) => {
      let objectUrl: string | null = null;
      setIsPreviewLoading(true);
      setPreviewError('');

      try {
        const token = await getToken({ skipCache: true });
        const blob = await fetchExportPdfBlob(
          activeTaskId,
          `format=pdf&output_type=bilingual&v=${previewVersion}`,
          token
        );
        const pdfBlob = blob.type === 'application/pdf' ? blob : new Blob([blob], { type: 'application/pdf' });
        objectUrl = URL.createObjectURL(pdfBlob);
        setPreviewBlob(pdfBlob);
        setPreviewObjectUrl((current) => {
          if (current) {
            URL.revokeObjectURL(current);
          }
          return objectUrl;
        });
      } catch (previewLoadError) {
        setPreviewBlob(null);
        setPreviewError(
          previewLoadError instanceof Error
            ? previewLoadError.message
            : 'Failed to load preview. Please try downloading the file instead.'
        );
        setIsPreviewLoading(false);
      }
    },
    [getToken, previewVersion]
  );

  const loadOriginalPreview = useCallback(async () => {
    if (!fileId || !isLoaded || !isSignedIn) {
      return;
    }

    try {
      const token = await getToken({ skipCache: true });
      const blob = await getOriginalFilePreviewBlob(fileId, token);
      const imageBlob = blob.type.startsWith('image/') ? blob : new Blob([blob], { type: 'image/png' });
      const objectUrl = URL.createObjectURL(imageBlob);
      setOriginalPreviewObjectUrl((current) => {
        if (current) {
          URL.revokeObjectURL(current);
        }
        return objectUrl;
      });
    } catch {
      setOriginalPreviewObjectUrl(null);
    }
  }, [fileId, getToken, isLoaded, isSignedIn]);

  const startTranslate = async () => {
    if (!fileId) {
      return;
    }
    if (!isSignedIn) {
      setError('Please sign in before translating this file.');
      return;
    }
    if (isStartBlocked) {
      setError('This file exceeds your current plan limits. Please upgrade to continue.');
      return;
    }

    setIsStarting(true);
    setError('');
    setProgress((current) => ({
      ...current,
      status: 'processing',
      progress: current.progress || 0,
      processedPages: current.processedPages || 0,
      translatedPages: current.translatedPages || 0,
      totalPages: current.totalPages || initialTotalPages,
      requestedPages: current.requestedPages || initialTotalPages,
    }));

    try {
      const token = await getToken({ skipCache: true });
      const response = await startTranslation({ fileId, sourceLang, targetLang }, token);
      if (!response.success) {
        throw new Error('Failed to start translation.');
      }
      setTaskId(response.taskId);
      setProgress((current) => ({
        ...current,
        status: 'processing',
        progress: current.progress || 0,
        totalPages: response.totalPages || current.totalPages || initialTotalPages,
        requestedPages: response.requestedPages,
        isPartial: response.isPartial,
      }));
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : 'An error occurred.');
    } finally {
      setIsStarting(false);
    }
  };

  const pollProgress = useCallback(async () => {
    if (!taskId || isPollingRef.current) {
      return;
    }

    isPollingRef.current = true;
    try {
      const token = await getToken({ skipCache: true });
      const progressData = await getTranslationProgress(taskId, token);
      setProgress((current) => mergeProgress(current, progressData));

      if (progressData.status === 'completed') {
        pollErrorCountRef.current = 0;
        setError('');
        setIsPreparingPreview(true);
        const resultData = await getTranslationResult(taskId, false, token);
        setResult(resultData);
        setIsPreparingPreview(false);
        await loadPreview(taskId);
      } else if (progressData.status === 'error') {
        pollErrorCountRef.current = 0;
        setError(progressData.error || 'Translation task failed.');
      } else {
        pollErrorCountRef.current = 0;
        setError('');
      }
    } catch (pollError) {
      setIsPreparingPreview(false);
      pollErrorCountRef.current += 1;
      if (pollErrorCountRef.current >= 3) {
        setError(pollError instanceof Error ? pollError.message : 'Failed to get translation progress.');
      }
    } finally {
      isPollingRef.current = false;
    }
  }, [getToken, loadPreview, mergeProgress, taskId]);

  useEffect(() => {
    loadUsage();
  }, [loadUsage]);

  useEffect(() => {
    loadOriginalPreview();
  }, [loadOriginalPreview]);

  useEffect(() => {
    return () => {
      if (originalPreviewObjectUrl) {
        URL.revokeObjectURL(originalPreviewObjectUrl);
      }
    };
  }, [originalPreviewObjectUrl]);

  useEffect(() => {
    return () => {
      if (previewObjectUrl) {
        URL.revokeObjectURL(previewObjectUrl);
      }
    };
  }, [previewObjectUrl]);

  useEffect(() => {
    if (!previewObjectUrl) {
      setPreviewBlob(null);
    }
  }, [previewObjectUrl]);

  useEffect(() => {
    if (!downloadToast || downloadToast.type === 'loading') {
      return;
    }

    const timer = window.setTimeout(() => {
      setDownloadToast(null);
    }, 2600);

    return () => window.clearTimeout(timer);
  }, [downloadToast]);

  useEffect(() => {
    if (!fileId) {
      router.push('/');
    }
  }, [fileId, router]);

  useEffect(() => {
    if (!isRestoringCompletedTask && taskId && progress.status === 'processing' && !result) {
      void pollProgress();
      const timer = window.setInterval(() => {
        void pollProgress();
      }, 2000);

      return () => window.clearInterval(timer);
    }
  }, [isRestoringCompletedTask, pollProgress, progress.status, result, taskId]);

  useEffect(() => {
    if (!initialTaskId || !isProcessingHistoryEntry || taskId || result) {
      return;
    }

    setTaskId(initialTaskId);
    setProgress((current) => ({
      ...current,
      status: 'processing',
      totalPages: current.totalPages || initialTotalPages,
      requestedPages: current.requestedPages || initialTotalPages,
    }));
  }, [initialTaskId, initialTotalPages, isProcessingHistoryEntry, result, taskId]);

  useEffect(() => {
    async function loadExistingResult() {
      if (
        !initialTaskId ||
        !isCompletedHistoryEntry ||
        !isLoaded ||
        !isSignedIn ||
        result ||
        restoredCompletedTaskIdRef.current === initialTaskId
      ) {
        return;
      }

      restoredCompletedTaskIdRef.current = initialTaskId;
      setIsPreparingPreview(true);
      setIsRestoringCompletedTask(true);
      setError('');

      try {
        const token = await getToken({ skipCache: true });
        const progressData = await getTranslationProgress(initialTaskId, token);
        setProgress((current) => mergeProgress(current, progressData));

        if (progressData.status === 'completed') {
          setTaskId(initialTaskId);
          const resultData = await getTranslationResult(initialTaskId, false, token);
          setResult(resultData);
          await loadPreview(initialTaskId);
        } else if (progressData.status === 'processing') {
          setTaskId(initialTaskId);
        } else {
          setError(progressData.error || 'Translation task failed.');
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : 'Failed to load translation result.');
      } finally {
        setIsPreparingPreview(false);
        setIsRestoringCompletedTask(false);
      }
    }

    loadExistingResult();
  }, [getToken, initialTaskId, isCompletedHistoryEntry, isLoaded, isSignedIn, loadPreview, mergeProgress, result]);

  const handleDownload = async (type: DownloadType) => {
    if (!taskId || downloadingType) {
      return;
    }

    setIsDownloadOpen(false);
    setDownloadingType(type);
    setDownloadToast({
      type: 'loading',
      message: type === 'bilingual' ? 'Preparing bilingual PDF...' : 'Preparing translation-only PDF...',
    });
    try {
      const token = await getToken({ skipCache: true });
      const blob =
        type === 'bilingual' && previewBlob
          ? previewBlob
          : await exportTranslation(taskId, type === 'bilingual' ? 'pdf_bilingual' : 'pdf_translated', token);
      const pdfBlob = blob.type === 'application/pdf' ? blob : new Blob([blob], { type: 'application/pdf' });
      const objectUrl = URL.createObjectURL(pdfBlob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = `${displayFileName.replace(/\.pdf$/i, '')}_${type}.pdf`;
      document.body.appendChild(link);
      link.click();
      window.setTimeout(() => {
        if (link.parentNode) {
          link.parentNode.removeChild(link);
        }
        URL.revokeObjectURL(objectUrl);
      }, 0);
      setDownloadToast({
        type: 'success',
        message: 'Download started.',
      });
    } catch (downloadError) {
      setDownloadToast({
        type: 'error',
        message: downloadError instanceof Error ? downloadError.message : 'Failed to download file.',
      });
    } finally {
      setDownloadingType(null);
    }
  };

  const handleClose = () => {
    router.back();
  };

  if (!fileId) {
    return null;
  }

  if (isLoaded && !isSignedIn) {
    return (
      <div className="app-shell">
        <div className="border-b border-slate-100 bg-white">
          <div className="flex h-14 items-center px-4">
            <button type="button" onClick={handleClose} className="text-slate-400 transition-colors hover:text-slate-900">
              <X className="size-4" strokeWidth={2} />
            </button>
          </div>
        </div>
        <div className="flex min-h-[calc(100vh-56px)] items-center justify-center px-4">
          <div className="w-full max-w-[560px] rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-[var(--shadow-card)]">
            <h1 className="text-[40px] font-bold tracking-[-0.05em] text-slate-900">Sign in required</h1>
            <p className="mt-4 text-[16px] leading-relaxed text-slate-600">Please sign in to translate files and access your private results.</p>
            <div className="mt-8">
              <SignInButton mode="modal">
                <button className="rounded-lg bg-slate-900 px-4 py-2 text-[13px] font-semibold text-white">Sign in</button>
              </SignInButton>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell flex h-screen flex-col overflow-hidden bg-white">
      <div className="border-b border-slate-100 bg-white">
        <div className="flex h-14 w-full items-center justify-between px-4">
          <button
            type="button"
            onClick={handleClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-900"
            aria-label="Close"
          >
            <X className="size-4" strokeWidth={2} />
          </button>

          <div className="flex flex-1 justify-center">
            <div className="flex items-center gap-3">
              <LanguageSelector
                sourceLang={sourceLang}
                targetLang={targetLang}
                onSourceLangChange={setSourceLang}
                onTargetLangChange={setTargetLang}
                disabled={isProcessing || Boolean(result) || isStarting}
              />
              {result ? (
                <span className="inline-flex items-center gap-1.5 rounded-lg border border-green-200 bg-green-50 px-4 py-1.5 text-[13px] font-medium text-green-700">
                  <CheckCircle2 className="size-4" strokeWidth={2} />
                  Complete
                </span>
              ) : (
                <button
                  type="button"
                  onClick={startTranslate}
                  disabled={!isLoaded || !isSignedIn || isProcessing || isStarting || isStartBlocked}
                  className={`rounded-lg px-4 py-1.5 text-[13px] font-semibold text-white transition-colors ${
                    isProcessing || isStarting ? 'bg-slate-300 text-slate-500' : 'bg-emerald-600 hover:bg-emerald-700'
                  } disabled:cursor-not-allowed`}
                >
                  {isStarting ? 'Starting...' : isProcessing ? 'Translating...' : 'Translate'}
                </button>
              )}
            </div>
          </div>

          <div className="flex min-w-[112px] justify-end">
            {isPreviewReady ? (
              <div className="flex items-center gap-2">
                <div className="group relative">
                  <button
                    type="button"
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                    aria-label="Download help"
                  >
                    <Info className="size-4" strokeWidth={2} />
                  </button>
                  <div className="pointer-events-none absolute right-0 top-[calc(100%+8px)] z-20 w-[320px] rounded-xl border border-slate-200 bg-white p-3 text-left text-[12px] leading-5 text-slate-600 opacity-0 shadow-xl transition-opacity duration-150 group-hover:opacity-100">
                    Tip: Use the editor&apos;s Save button to keep any annotations. The Download button exports the translated file only.
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setIsDownloadOpen(true)}
                  className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-slate-800"
                >
                  <Download className="size-4" strokeWidth={2} />
                  Download
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {!result ? (
        <PreviewPlaceholder
          title={
            isRestoringCompletedResult
              ? 'Loading translated document'
              : isStartingTranslation
                ? 'Translating your document'
                : 'Ready to translate'
          }
          description={
            isRestoringCompletedResult
              ? 'Preparing your translated PDF...'
              : isStartingTranslation
              ? 'Please wait while we translate your PDF...'
              : 'Select your target language and click the "Translate" button above to start translating your document.'
          }
          originalPreviewUrl={originalPreviewUrl}
          processing={isStartingTranslation || isRestoringCompletedResult}
          error={error}
          footer={
            <div className="space-y-4">
              {!isStartingTranslation && !isRestoringCompletedResult ? (
                <p className="text-[15px] font-medium text-slate-500">
                  {labelForLang(sourceLang)} <ArrowLeftRight className="mx-1 inline size-4" strokeWidth={2} /> {labelForLang(targetLang)}
                </p>
              ) : null}

              {isStartingTranslation && !isRestoringCompletedResult ? (
                <div className="mx-auto w-full max-w-[420px]">
                  <ProgressBar progress={progress} />
                </div>
              ) : !isRestoringCompletedResult ? (
                <div className="rounded-xl border border-slate-200 bg-white px-6 py-3 text-[14px] font-medium text-slate-500">
                  {statusSummaryParts.map((part, index) => (
                    <span
                      key={part}
                      className={
                        part.startsWith('Remaining:')
                          ? remainingPagesToneClass
                          : index === 0
                            ? 'font-semibold text-slate-700'
                            : undefined
                      }
                    >
                      {index > 0 ? ' | ' : ''}
                      {part}
                    </span>
                  ))}
                </div>
              ) : null}

              {isFreePlan && !isStartingTranslation && !isRestoringCompletedResult && usage ? (
                <p className="mx-auto max-w-[420px] text-[13px] leading-6 text-slate-400">
                  Free plan translates the first {usage.freePreviewPages} page{usage.freePreviewPages === 1 ? '' : 's'} of each PDF as a preview.
                </p>
              ) : null}

              {isFreePlan && !isStartingTranslation && !isRestoringCompletedResult && usage ? (
                <a href="/pricing" className="inline-flex text-[13px] font-semibold text-emerald-600">
                  View plans and limits
                </a>
              ) : null}

              {isStartBlocked && usage && !isStartingTranslation && !isRestoringCompletedResult ? (
                <div className="inline-flex items-center gap-2 text-[13px] font-semibold">
                  <span className="text-orange-600">Not enough remaining pages</span>
                  <a href="/pricing" className="text-emerald-600">
                    View plans and limits
                  </a>
                </div>
              ) : null}
            </div>
          }
        />
      ) : !previewUrl ? (
        <PreviewPlaceholder
          title="Loading translated document"
          description="Preparing your translated PDF..."
          originalPreviewUrl={originalPreviewUrl}
          processing
          error={previewError}
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-50">
          <div className="w-full min-h-0 flex-1">
            <div className="relative h-full w-full overflow-hidden bg-white">
              {(isPreparingPreview || isPreviewLoading || previewError) && (
                <div className="absolute inset-0 z-10">
                  <PreviewPlaceholder
                    title="Loading translated document"
                    description="Preparing your translated PDF..."
                    originalPreviewUrl={originalPreviewUrl}
                    processing={!previewError}
                    error={previewError}
                    overlay
                  />
                </div>
              )}

              <iframe
                key={previewUrl}
                src={previewUrl}
                title="Bilingual file preview"
                onLoad={() => setIsPreviewLoading(false)}
                className={`h-full w-full transition-opacity duration-200 ${
                  isPreparingPreview || isPreviewLoading || previewError ? 'opacity-0' : 'opacity-100'
                }`}
              />
            </div>
          </div>
        </div>
      )}

      <div className="border-t border-slate-100 bg-white px-4 text-[12px] text-slate-400">
        <div className="flex h-9 w-full flex-col justify-center gap-1 overflow-hidden sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-3">
            <span>Document: {displayFileName}</span>
            <span>|</span>
            <span>{knownTotalPages} pages</span>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {result ? (
              <>
                <span className="font-medium text-emerald-600">Translation completed</span>
                {usage ? <span>| {formatPlanName(usage.plan)}: {usage.remainingPages ?? 'Unlimited'} pages remaining this month</span> : null}
              </>
            ) : (
              <>
                {usage ? <span>{formatPlanName(usage.plan)}: {usage.remainingPages ?? 'Unlimited'} pages remaining this month</span> : null}
              </>
            )}
          </div>
        </div>
      </div>

      <DownloadModal
        open={isDownloadOpen}
        filename={displayFileName}
        onClose={() => setIsDownloadOpen(false)}
        onDownload={handleDownload}
      />
      <DownloadToast toast={downloadToast} />
    </div>
  );
}

export default function TranslatePage() {
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return <ClerkSetupRequired />;
  }

  return <TranslatePageContent />;
}
