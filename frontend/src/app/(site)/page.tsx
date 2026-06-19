'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, ArrowLeftRight, Check, FileText, ShieldCheck, Sparkles } from 'lucide-react';
import { FileUploader } from '@/components/FileUploader';
import { uploadFile } from '@/lib/api';

const SIGN_IN_UPLOAD_ERROR = 'Please sign in to upload a PDF.';
const SESSION_EXPIRED_ERROR = 'Please sign in again to upload your PDF.';
const AUTH_LOADING_ERROR = 'Getting your account ready. Try again in a moment.';
const AUTH_LOAD_TIMEOUT_ERROR = "We couldn't load your account. Refresh the page and try again.";

type UploadNotice = {
  tone: 'warning' | 'error';
  message: string;
};

function ClerkSetupRequired() {
  return (
    <div className="app-shell">
      <section className="page-container py-24">
        <div className="mx-auto max-w-[560px] rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-[var(--shadow-card)]">
          <h1 className="text-[40px] font-bold tracking-[-0.05em] text-slate-900">Clerk setup required</h1>
          <p className="mt-4 text-[16px] leading-relaxed text-slate-600">
            Add your Clerk publishable key to <span className="font-semibold">frontend/.env.local</span> before using login and uploads.
          </p>
        </div>
      </section>
    </div>
  );
}

function FeaturePill({ children }: { children: React.ReactNode }) {
  return (
    <div className="inline-flex items-center gap-2 text-[14px] font-medium text-slate-500">
      <span className="flex size-4 items-center justify-center rounded-full border border-emerald-500 text-emerald-600">
        <Check className="size-2.5" strokeWidth={2.5} />
      </span>
      {children}
    </div>
  );
}

function WhyCard({
  icon,
  title,
  description,
  accent,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  accent: string;
}) {
  return (
    <div className="mx-auto max-w-[320px]">
      <div className={`mb-5 flex h-11 w-11 items-center justify-center rounded-2xl text-white shadow-md ${accent}`}>
        {icon}
      </div>
      <h3 className="text-[20px] font-semibold tracking-[-0.02em] text-slate-900">{title}</h3>
      <p className="mt-3 text-[16px] leading-7 text-slate-600">{description}</p>
    </div>
  );
}

function Footer() {
  return (
    <footer className="border-t border-slate-100">
      <div className="page-container flex flex-col gap-4 py-8 text-[13px] text-slate-400 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-4">
          <span>(c) 2026 LingoDoc</span>
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
          <Link href="/refund">Refunds</Link>
          <Link href="/help">Help</Link>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span>support@lingodoc.xyz</span>
          <span>-</span>
          <span>Made with care for translators</span>
        </div>
      </div>
    </footer>
  );
}

function HomeContent() {
  const router = useRouter();
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [isUploading, setIsUploading] = useState(false);
  const [uploadNotice, setUploadNotice] = useState<UploadNotice | null>(null);
  const [authLoadTimedOut, setAuthLoadTimedOut] = useState(false);
  const [noticeShakeKey, setNoticeShakeKey] = useState(0);

  useEffect(() => {
    if (isSignedIn && uploadNotice?.message === SIGN_IN_UPLOAD_ERROR) {
      setUploadNotice(null);
    }
  }, [isSignedIn, uploadNotice?.message]);

  useEffect(() => {
    router.prefetch('/translate');
  }, [router]);

  useEffect(() => {
    if (isLoaded) {
      setAuthLoadTimedOut(false);
      return;
    }

    const timeout = window.setTimeout(() => {
      setAuthLoadTimedOut(true);
    }, 5000);

    return () => window.clearTimeout(timeout);
  }, [isLoaded]);

  const handleFileUpload = async (file: File) => {
    if (!isLoaded) {
      setUploadNotice({
        tone: 'warning',
        message: authLoadTimedOut ? AUTH_LOAD_TIMEOUT_ERROR : AUTH_LOADING_ERROR,
      });
      return false;
    }

    if (!isSignedIn) {
      setUploadNotice({ tone: 'warning', message: SIGN_IN_UPLOAD_ERROR });
      return false;
    }

    setIsUploading(true);
    setUploadNotice(null);

    try {
      const token = await getToken({ skipCache: true });
      if (!token) {
        setUploadNotice({
          tone: 'warning',
          message: isSignedIn ? SESSION_EXPIRED_ERROR : SIGN_IN_UPLOAD_ERROR,
        });
        return false;
      }
      const response = await uploadFile(file, token);
      if (!response.success) {
        throw new Error('Failed to upload file.');
      }

      const params = new URLSearchParams({
        fileId: response.fileId,
        filename: response.filename || file.name,
        totalPages: String(response.totalPages),
        sourceLang: 'en',
        targetLang: 'zh',
      });
      router.push(`/translate?${params.toString()}`);
      return true;
    } catch (uploadError) {
      setUploadNotice({
        tone: 'error',
        message: uploadError instanceof Error ? uploadError.message : 'An error occurred during upload.',
      });
      return false;
    } finally {
      setIsUploading(false);
    }
  };

  const handleBlockedUploadAttempt = () => {
    setUploadNotice({
      tone: 'warning',
      message: !isLoaded
        ? authLoadTimedOut
          ? AUTH_LOAD_TIMEOUT_ERROR
          : AUTH_LOADING_ERROR
        : SIGN_IN_UPLOAD_ERROR,
    });
    setNoticeShakeKey((key) => key + 1);
  };

  const visibleUploadNotice =
    uploadNotice ||
    (isLoaded && !isSignedIn
      ? {
          tone: 'warning' as const,
          message: SIGN_IN_UPLOAD_ERROR,
        }
      : null);

  return (
    <div className="app-shell">
      <main>
        <section className="page-container flex flex-col items-center pb-20 pt-8 text-center sm:pb-28 sm:pt-14">
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1 text-[14px] font-semibold text-emerald-600">
            <Sparkles className="size-3" strokeWidth={2} />
            AI-powered PDF translation
          </span>

          <h1 className="mt-8 max-w-[860px] text-[56px] font-bold leading-[1.1] tracking-[-0.06em] text-slate-900">
            Translate PDFs with
            <br />
            bilingual side-by-side view
          </h1>

          <p className="mt-5 max-w-[720px] text-[17px] leading-relaxed text-slate-600">
            Translate PDFs for review and reading, compare source and translation side-by-side,
            and work with larger documents without blocking preview.
          </p>

          <div className="mt-12 w-full max-w-[860px]">
            <FileUploader
              onFileUpload={handleFileUpload}
              disabled={isUploading}
              keepLoadingOnSuccess
              onBlockedUploadAttempt={!isLoaded || !isSignedIn ? handleBlockedUploadAttempt : undefined}
            />
            <p className="mt-4 text-center text-[12px] font-medium text-slate-400">Supports large PDF files</p>
            {visibleUploadNotice && (
              <p
                key={noticeShakeKey}
                className={`mt-4 text-center text-sm font-semibold ${
                  visibleUploadNotice.tone === 'warning' ? 'text-amber-700' : 'text-red-600'
                } ${noticeShakeKey > 0 ? 'animate-upload-notice-shake' : ''}`}
              >
                {visibleUploadNotice.message}
              </p>
            )}
          </div>

          <div className="mt-10 flex flex-wrap items-center justify-center gap-x-8 gap-y-3">
            <FeaturePill>Layout-aware translation</FeaturePill>
            <FeaturePill>Side-by-side comparison</FeaturePill>
            <FeaturePill>Bilingual PDF export</FeaturePill>
          </div>
        </section>

        <section className="border-y border-slate-100 bg-white">
          <div className="page-container py-16 sm:py-24">
            <p className="text-center text-[12px] font-bold tracking-[0.08em] text-slate-500">WHY LINGODOC</p>
            <h2 className="mt-4 text-center text-[28px] font-bold tracking-[-0.04em] text-slate-900">
              PDF translation for review and reading
            </h2>

            <div className="mt-16 grid gap-10 lg:grid-cols-3">
              <WhyCard
                icon={<ShieldCheck className="size-5" strokeWidth={2} />}
                title="Layout-aware output"
                description="Designed to keep tables, images, fonts, and formatting close to the original where possible."
                accent="bg-gradient-to-br from-slate-900 to-slate-700"
              />
              <WhyCard
                icon={<ArrowLeftRight className="size-5" strokeWidth={2} />}
                title="Side-by-side reading"
                description="Compare original and translation in a split view. Perfect for learning or verifying translations."
                accent="bg-gradient-to-br from-emerald-600 to-emerald-500"
              />
              <WhyCard
                icon={<FileText className="size-5" strokeWidth={2} />}
                title="Flexible export"
                description="Download bilingual PDFs with side-by-side view, or translation-only versions for larger document workflows."
                accent="bg-gradient-to-br from-slate-700 to-slate-600"
              />
            </div>
          </div>
        </section>

        <section className="page-container py-14 sm:py-20">
          <div className="mx-auto max-w-[820px] rounded-[28px] bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 px-8 py-14 text-center text-white shadow-xl">
            <h2 className="text-[48px] font-bold tracking-[-0.05em]">Ready to translate?</h2>
            <p className="mx-auto mt-4 max-w-[620px] text-[17px] leading-relaxed text-slate-300">
              PDF translation for review and reading, with bilingual output and layout-aware rendering.
            </p>
            <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
              <button
                type="button"
                onClick={() => router.push('/')}
                className="inline-flex items-center gap-2 rounded-xl bg-white px-5 py-3 text-[14px] font-semibold text-slate-900 transition-all hover:-translate-y-0.5"
              >
                Upload your first file
                <ArrowRight className="size-4" strokeWidth={2} />
              </button>
              <button
                type="button"
                onClick={() => router.push('/pricing')}
                className="inline-flex items-center rounded-xl bg-slate-700 px-5 py-3 text-[14px] font-semibold text-white transition-colors hover:bg-slate-600"
              >
                View pricing
              </button>
            </div>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}

export default function Home() {
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return <ClerkSetupRequired />;
  }

  return <HomeContent />;
}
