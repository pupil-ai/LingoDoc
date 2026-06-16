'use client';

import type { ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SignInButton, useAuth } from '@clerk/nextjs';
import { useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeftRight, CheckCircle2, ChevronLeft, ChevronRight, Download, FileText, Info, Loader2, Minus, Plus, X } from 'lucide-react';
import { LanguageSelector } from '@/components/LanguageSelector';
import { ProgressBar } from '@/components/ProgressBar';
import {
  buildUrl,
  getExportJob,
  getMyUsage,
  getOriginalFilePreviewBlob,
  getTranslationPagePreviewBlob,
  getTranslationProgress,
  getTranslationResult,
  startExportJob,
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

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
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
            alt="PDF preview background"
            className="h-full max-h-full w-auto max-w-full object-contain opacity-70"
          />
        </div>
      ) : (
        <div className="absolute inset-0 bg-gradient-to-br from-slate-100 via-white to-slate-100" />
      )}

      <div className="absolute inset-0 bg-white/55 backdrop-blur-sm" />
      <div className="absolute inset-0 bg-gradient-to-b from-white/70 via-white/80 to-white/90" />

      <div className="relative z-10 flex h-full w-full items-center justify-center overflow-y-auto px-6 py-10">
        <div className="grid w-full max-w-[540px] grid-rows-[auto_8rem] px-10 py-12 text-center">
          <div>
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50 to-emerald-100 text-emerald-600 shadow-sm">
              {processing ? <Loader2 className="size-8 animate-spin" strokeWidth={2} /> : <ArrowLeftRight className="size-8" strokeWidth={2} />}
            </div>
            <h1 className="mt-8 text-[32px] font-bold tracking-[-0.04em] text-slate-900">{title}</h1>
            <p className="mt-4 text-[16px] leading-relaxed text-slate-500">{description}</p>
          </div>
          <div className="mt-8">
            {footer ? <div>{footer}</div> : null}
            {error ? <p className="mt-6 text-[14px] font-medium text-red-600">{error}</p> : null}
          </div>
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

function PreviewControls({
  page,
  totalPages,
  zoom,
  loading,
  onPageChange,
  onZoomChange,
}: {
  page: number;
  totalPages: number;
  zoom: number;
  loading: boolean;
  onPageChange: (page: number) => void;
  onZoomChange: (zoom: number) => void;
}) {
  const canGoBack = page > 1 && !loading;
  const canGoForward = page < totalPages && !loading;
  const safeTotalPages = Math.max(totalPages, 1);

  return (
    <div className="flex flex-wrap items-center justify-center gap-3 sm:gap-5">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={!canGoBack}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-300"
          aria-label="Previous page"
        >
          <ChevronLeft className="size-4" strokeWidth={2} />
        </button>
        <div className="min-w-[112px] text-center text-[13px] font-medium text-slate-600">
          {page} / {safeTotalPages}
        </div>
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={!canGoForward}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-300"
          aria-label="Next page"
        >
          <ChevronRight className="size-4" strokeWidth={2} />
        </button>
      </div>

      <div className="hidden h-5 w-px bg-slate-200 sm:block" aria-hidden="true" />

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onZoomChange(Math.max(0.7, Number((zoom - 0.1).toFixed(2))))}
          disabled={zoom <= 0.7}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-300"
          aria-label="Zoom out"
        >
          <Minus className="size-4" strokeWidth={2} />
        </button>
        <div className="min-w-[52px] text-center text-[12px] font-semibold text-slate-500">{Math.round(zoom * 100)}%</div>
        <button
          type="button"
          onClick={() => onZoomChange(Math.min(1.8, Number((zoom + 0.1).toFixed(2))))}
          disabled={zoom >= 1.8}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-300"
          aria-label="Zoom in"
        >
          <Plus className="size-4" strokeWidth={2} />
        </button>
      </div>
    </div>
  );
}

function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === 'undefined') {
      return;
    }

    const updateSize = (width: number, height: number) => {
      setSize((current) => {
        if (current.width === width && current.height === height) {
          return current;
        }

        return { width, height };
      });
    };

    updateSize(node.clientWidth, node.clientHeight);

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }

      updateSize(entry.contentRect.width, entry.contentRect.height);
    });

    observer.observe(node);

    return () => observer.disconnect();
  }, []);

  return [ref, size] as const;
}

function TranslatedPagePreview({
  imageUrl,
  page,
  zoom,
  loading,
  error,
  originalPreviewUrl,
}: {
  imageUrl: string | null;
  page: number;
  totalPages: number;
  zoom: number;
  loading: boolean;
  error: string;
  originalPreviewUrl: string | null;
  onPageChange: (page: number) => void;
  onZoomChange: (zoom: number) => void;
}) {
  const previewPadding = 24;
  const [previewViewportRef, previewViewportSize] = useElementSize<HTMLDivElement>();
  const [imageNaturalSize, setImageNaturalSize] = useState({ width: 0, height: 0 });
  const fitScale = useMemo(() => {
    if (!imageUrl || !imageNaturalSize.width || !imageNaturalSize.height || !previewViewportSize.width || !previewViewportSize.height) {
      return 1;
    }

    const availableWidth = Math.max(previewViewportSize.width - previewPadding * 2, 1);
    const availableHeight = Math.max(previewViewportSize.height - previewPadding * 2, 1);

    return Math.min(availableWidth / imageNaturalSize.width, availableHeight / imageNaturalSize.height, 1);
  }, [imageNaturalSize.height, imageNaturalSize.width, imageUrl, previewViewportSize.height, previewViewportSize.width]);
  const displayScale = fitScale * zoom;
  const renderWidth = imageNaturalSize.width ? Math.round(imageNaturalSize.width * displayScale) : 0;
  const renderHeight = imageNaturalSize.height ? Math.round(imageNaturalSize.height * displayScale) : 0;
  const isPreviewOverflowing =
    renderWidth > Math.max(previewViewportSize.width - previewPadding * 2, 0) ||
    renderHeight > Math.max(previewViewportSize.height - previewPadding * 2, 0);

  useEffect(() => {
    setImageNaturalSize({ width: 0, height: 0 });
  }, [imageUrl]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-100">
      <div ref={previewViewportRef} className="relative min-h-0 flex-1 overflow-auto overscroll-contain">
        {loading ? (
          <div className="absolute inset-0 z-10">
            <PreviewPlaceholder
              title="Preparing page preview"
              description="Rendering the selected page..."
              originalPreviewUrl={imageUrl || originalPreviewUrl}
              processing
              overlay
            />
          </div>
        ) : null}

        {error ? (
          <div className="flex h-full items-center justify-center px-6 text-center">
            <div className="max-w-[420px] rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-[13px] font-medium leading-6 text-red-700">
              {error}
            </div>
          </div>
        ) : imageUrl ? (
          <div
            className={`flex h-full min-h-full w-full p-6 ${
              isPreviewOverflowing ? 'items-start justify-center' : 'items-center justify-center'
            }`}
          >
            <img
              src={imageUrl}
              alt={`Translated preview page ${page}`}
              onLoad={(event) => {
                const { naturalWidth, naturalHeight } = event.currentTarget;
                setImageNaturalSize((current) => {
                  if (current.width === naturalWidth && current.height === naturalHeight) {
                    return current;
                  }

                  return { width: naturalWidth, height: naturalHeight };
                });
              }}
              style={
                renderWidth
                  ? {
                      width: `${renderWidth}px`,
                      height: 'auto',
                    }
                  : {
                      maxWidth: '100%',
                      maxHeight: '100%',
                    }
              }
              className="shrink-0 border border-slate-200 bg-white object-contain shadow-sm"
            />
          </div>
        ) : (
          <PreviewPlaceholder
            title="Preparing page preview"
            description="Rendering the selected page..."
            originalPreviewUrl={imageUrl || originalPreviewUrl}
            processing
            overlay
          />
        )}
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
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewPageImageUrl, setPreviewPageImageUrl] = useState<string | null>(null);
  const previewPageImageUrlRef = useRef<string | null>(null);
  const [previewPage, setPreviewPage] = useState(1);
  const [previewZoom, setPreviewZoom] = useState(1);
  const [previewError, setPreviewError] = useState('');
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
  const previewPageCount = Math.max(result?.translatedPages || result?.pages?.length || progress.translatedPages || progress.requestedPages || knownTotalPages || 1, 1);
  const isPreviewReady = Boolean(result && previewPageImageUrl && !isPreparingPreview && !previewError);

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

  const loadPreviewPage = useCallback(
    async (activeTaskId: string, pageNumber: number) => {
      setIsPreviewLoading(true);
      setPreviewError('');

      try {
        const token = await getToken({ skipCache: true });
        const blob = await getTranslationPagePreviewBlob(activeTaskId, token, pageNumber);
        const imageBlob = blob.type.startsWith('image/') ? blob : new Blob([blob], { type: 'image/png' });
        const objectUrl = URL.createObjectURL(imageBlob);

        if (previewPageImageUrlRef.current) {
          URL.revokeObjectURL(previewPageImageUrlRef.current);
        }
        previewPageImageUrlRef.current = objectUrl;
        setPreviewPageImageUrl(objectUrl);
        setPreviewPage(pageNumber);
      } catch (previewLoadError) {
        if (previewPageImageUrlRef.current) {
          URL.revokeObjectURL(previewPageImageUrlRef.current);
          previewPageImageUrlRef.current = null;
        }
        setPreviewPageImageUrl(null);
        setPreviewError(
          previewLoadError instanceof Error
            ? previewLoadError.message
            : 'Failed to load preview. Please try downloading the file instead.'
        );
      } finally {
        setIsPreviewLoading(false);
      }
    },
    [getToken]
  );

  const loadPreview = useCallback(
    async (activeTaskId: string, previewPath?: string) => {
      setPreviewUrl(previewPath || activeTaskId);
      setPreviewPage(1);
      await loadPreviewPage(activeTaskId, 1);
    },
    [loadPreviewPage]
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

  const handlePreviewPageChange = useCallback(
    (nextPage: number) => {
      if (!taskId || isPreviewLoading) {
        return;
      }

      const safePage = Math.min(Math.max(nextPage, 1), previewPageCount);
      if (safePage === previewPage) {
        return;
      }

      void loadPreviewPage(taskId, safePage);
    },
    [isPreviewLoading, loadPreviewPage, previewPage, previewPageCount, taskId]
  );

  useEffect(() => {
    return () => {
      if (previewPageImageUrlRef.current) {
        URL.revokeObjectURL(previewPageImageUrlRef.current);
        previewPageImageUrlRef.current = null;
      }
    };
  }, []);

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
        await loadPreview(taskId, resultData.previewUrl);
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
          await loadPreview(initialTaskId, resultData.previewUrl);
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
      let exportJob = await startExportJob(taskId, type, token);
      if (exportJob.status === 'error') {
        throw new Error(exportJob.error || 'Failed to prepare export file.');
      }

      const maxPolls = 7200;
      for (let attempt = 0; exportJob.status !== 'ready' && attempt < maxPolls; attempt += 1) {
        setDownloadToast({
          type: 'loading',
          message: type === 'bilingual' ? 'Rendering bilingual PDF...' : 'Rendering translation-only PDF...',
        });
        await wait(2000);
        exportJob = await getExportJob(taskId, type, token);
        if (exportJob.status === 'error') {
          throw new Error(exportJob.error || 'Failed to prepare export file.');
        }
      }

      if (exportJob.status !== 'ready') {
        throw new Error('Export is still rendering. Please try again in a moment.');
      }

      setDownloadToast({
        type: 'loading',
        message: 'Starting download...',
      });
      if (!exportJob.downloadUrl) {
        throw new Error('Download URL is not ready. Please try again in a moment.');
      }

      const link = document.createElement('a');
      link.href = buildUrl(exportJob.downloadUrl);
      link.download = `${displayFileName.replace(/\.pdf$/i, '')}_${type}.pdf`;
      document.body.appendChild(link);
      link.click();
      window.setTimeout(() => {
        if (link.parentNode) {
          link.parentNode.removeChild(link);
        }
      }, 0);
      setDownloadToast({
        type: 'success',
        message: 'Download sent to browser.',
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
    <div className="app-shell fixed inset-0 flex h-[100dvh] max-h-[100dvh] flex-col overflow-hidden bg-white">
      <div className="shrink-0 border-b border-slate-100 bg-white">
        <div className="flex h-14 w-full items-center justify-between px-4">
          <button
            type="button"
            onClick={handleClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-900"
            aria-label="Close"
          >
            <X className="size-4" strokeWidth={2} />
          </button>

          <div className="flex flex-1 justify-center px-4">
            <div className="flex min-w-0 items-center justify-center">
              {result ? (
                <PreviewControls
                  page={previewPage}
                  totalPages={previewPageCount}
                  zoom={previewZoom}
                  loading={isPreparingPreview || isPreviewLoading}
                  onPageChange={handlePreviewPageChange}
                  onZoomChange={setPreviewZoom}
                />
              ) : (
                <div className="flex items-center gap-3">
                  <LanguageSelector
                    sourceLang={sourceLang}
                    targetLang={targetLang}
                    onSourceLangChange={setSourceLang}
                    onTargetLangChange={setTargetLang}
                    disabled={isProcessing || Boolean(result) || isStarting}
                  />
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
                </div>
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
              ? 'Translation completed'
              : isStartingTranslation
                ? 'Translating your document'
                : 'Ready to translate'
          }
          description={
            isRestoringCompletedResult
              ? 'Preparing preview PDF...'
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
          title="Translation completed"
          description="Preparing preview PDF..."
          originalPreviewUrl={originalPreviewUrl}
          processing
          error={previewError}
        />
      ) : (
        <TranslatedPagePreview
          imageUrl={previewPageImageUrl}
          page={previewPage}
          totalPages={previewPageCount}
          zoom={previewZoom}
          loading={isPreparingPreview || isPreviewLoading}
          error={previewError}
          originalPreviewUrl={originalPreviewUrl}
          onPageChange={handlePreviewPageChange}
          onZoomChange={setPreviewZoom}
        />
      )}

      <div className="shrink-0 border-t border-slate-100 bg-white px-4 text-[12px] text-slate-400">
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
