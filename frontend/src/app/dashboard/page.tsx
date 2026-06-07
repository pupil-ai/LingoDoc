'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { SignInButton, useAuth } from '@clerk/nextjs';
import { useRouter } from 'next/navigation';
import { AlertCircle, CheckCircle2, FileText, Loader2, Search, Trash2, Upload, X } from 'lucide-react';
import { Header } from '@/components/Header';
import { deleteMyFile, getMyFiles } from '@/lib/api';
import type { MyFileRecord } from '@/types';

const PAGE_SIZE = 10;

function ClerkSetupRequired() {
  return (
    <div className="app-shell">
      <Header />
      <section className="page-container py-24">
        <div className="mx-auto max-w-[560px] rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-[var(--shadow-card)]">
          <h1 className="text-[40px] font-bold tracking-[-0.05em] text-slate-900">Clerk setup required</h1>
          <p className="mt-4 text-[16px] leading-relaxed text-slate-600">
            Add your Clerk publishable key to <span className="font-semibold">frontend/.env.local</span> before using the file dashboard.
          </p>
        </div>
      </section>
    </div>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatRelativeTime(value: string): string {
  const diff = Date.now() - new Date(value).getTime();
  const minutes = Math.max(1, Math.floor(diff / 60000));
  if (minutes < 60) return minutes === 1 ? 'Just now' : `${minutes} minutes ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? '1 hour ago' : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return days === 1 ? 'Yesterday' : `${days} days ago`;
  const weeks = Math.floor(days / 7);
  return weeks === 1 ? '1 week ago' : `${weeks} weeks ago`;
}

function formatLanguageLabel(file: MyFileRecord): string {
  if (file.source_lang && file.target_lang) {
    return `${file.source_lang} -> ${file.target_lang}`;
  }
  return 'Not started';
}

function StatusPill({ file }: { file: MyFileRecord }) {
  if (file.status === 'completed') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-green-200 bg-green-50 px-2 py-1 text-[11px] font-medium text-green-700">
        <CheckCircle2 className="size-3.5" strokeWidth={2} />
        Completed
      </span>
    );
  }

  if (file.status === 'processing') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-700">
        <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
        {Math.round(file.progress || 0)}%
      </span>
    );
  }

  if (file.status === 'error') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-red-200 bg-red-50 px-2 py-1 text-[11px] font-medium text-red-700">
        <AlertCircle className="size-3.5" strokeWidth={2} />
        Failed
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-700">
      Uploaded
    </span>
  );
}

function DeleteModal({
  file,
  isDeleting,
  onCancel,
  onConfirm,
}: {
  file: MyFileRecord | null;
  isDeleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (!file) {
    return null;
  }

  return (
    <div className="overlay-scrim fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onCancel}>
      <div
        className="w-full max-w-md rounded-2xl bg-white p-8 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100"
          >
            <X className="size-4" strokeWidth={2} />
          </button>
        </div>

        <div className="mx-auto mt-[-2px] flex h-14 w-14 items-center justify-center rounded-2xl bg-red-500 text-white shadow-lg shadow-red-500/20">
          <Trash2 className="size-7" strokeWidth={2} />
        </div>

        <h3 className="mt-5 text-center text-[28px] font-bold tracking-[-0.04em] text-slate-900">Delete File?</h3>
        <p className="mt-2 text-center text-[16px] text-slate-500">This action cannot be undone</p>

        <div className="mt-7 rounded-2xl border border-slate-200 bg-slate-50 p-3">
          <div className="flex items-center gap-3 text-left">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-700 text-white">
              <FileText className="size-5" strokeWidth={2} />
            </div>
            <p className="truncate text-[15px] font-medium text-slate-700">{file.original_filename}</p>
          </div>
        </div>

        <div className="mt-7 flex gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 rounded-xl bg-slate-100 px-4 py-3 text-[14px] font-semibold text-slate-900 transition-colors hover:bg-slate-200"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isDeleting}
            className="flex-1 rounded-xl bg-red-600 px-4 py-3 text-[14px] font-semibold text-white transition-colors hover:bg-red-700 disabled:cursor-wait disabled:opacity-70"
          >
            {isDeleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Pagination({
  currentPage,
  totalPages,
  onChange,
}: {
  currentPage: number;
  totalPages: number;
  onChange: (page: number) => void;
}) {
  if (totalPages <= 1) {
    return null;
  }

  const pages: Array<number | 'ellipsis'> = [];
  const visiblePages = new Set([1, currentPage - 1, currentPage, currentPage + 1, totalPages]);
  for (let page = 1; page <= totalPages; page += 1) {
    if (visiblePages.has(page)) {
      pages.push(page);
    } else if (pages[pages.length - 1] !== 'ellipsis') {
      pages.push('ellipsis');
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => onChange(Math.max(1, currentPage - 1))}
        disabled={currentPage === 1}
        className="rounded-lg bg-slate-100 px-3 py-2 text-[13px] font-medium text-slate-400 disabled:cursor-not-allowed"
      >
        Previous
      </button>
      {pages.map((page, index) =>
        page === 'ellipsis' ? (
          <span key={`ellipsis-${index}`} className="px-1 text-slate-400">...</span>
        ) : (
          <button
            key={page}
            type="button"
            onClick={() => onChange(page)}
            className={`flex h-8 w-8 items-center justify-center rounded-lg text-[13px] font-semibold ${
              currentPage === page ? 'bg-slate-900 text-white' : 'border border-slate-200 bg-white text-slate-500'
            }`}
          >
            {page}
          </button>
        )
      )}
      <button
        type="button"
        onClick={() => onChange(Math.min(totalPages, currentPage + 1))}
        disabled={currentPage === totalPages}
        className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] font-medium text-slate-700 disabled:cursor-not-allowed disabled:text-slate-300"
      >
        Next
      </button>
    </div>
  );
}

function DashboardContent() {
  const router = useRouter();
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [files, setFiles] = useState<MyFileRecord[]>([]);
  const [search, setSearch] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState('');
  const [fileToDelete, setFileToDelete] = useState<MyFileRecord | null>(null);

  const loadFiles = useCallback(async () => {
    if (!isLoaded || !isSignedIn) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      const token = await getToken({ skipCache: true });
      const response = await getMyFiles(token);
      if (!response.success) {
        throw new Error('Failed to load your files.');
      }
      setFiles(response.files);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to load your files.');
    } finally {
      setIsLoading(false);
    }
  }, [getToken, isLoaded, isSignedIn]);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  const filteredFiles = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    if (!normalized) {
      return files;
    }

    return files.filter((file) => {
      const haystack = [file.original_filename, file.source_lang || '', file.target_lang || '', file.error || '']
        .join(' ')
        .toLowerCase();
      return haystack.includes(normalized);
    });
  }, [files, search]);

  const totalPages = Math.max(1, Math.ceil(filteredFiles.length / PAGE_SIZE));

  useEffect(() => {
    setCurrentPage((prev) => Math.min(prev, totalPages));
  }, [totalPages]);

  const paginatedFiles = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredFiles.slice(start, start + PAGE_SIZE);
  }, [currentPage, filteredFiles]);

  const stats = useMemo(() => {
    const completed = files.filter((file) => file.status === 'completed').length;
    const inProgress = files.filter((file) => file.status === 'processing').length;
    return {
      total: files.length,
      completed,
      inProgress,
    };
  }, [files]);

  const openFile = (file: MyFileRecord) => {
    const params = new URLSearchParams({
      fileId: file.id,
      filename: file.original_filename,
      totalPages: String(file.total_pages),
      sourceLang: file.source_lang || 'en',
      targetLang: file.target_lang || 'zh',
    });

    if (file.task_id) {
      params.set('taskId', file.task_id);
    }

    router.push(`/translate?${params.toString()}`);
  };

  const handleDelete = async () => {
    if (!fileToDelete) {
      return;
    }

    setIsDeleting(true);
    try {
      const token = await getToken({ skipCache: true });
      await deleteMyFile(fileToDelete.id, token);
      setFiles((current) => current.filter((file) => file.id !== fileToDelete.id));
      setFileToDelete(null);
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Failed to delete file.');
    } finally {
      setIsDeleting(false);
    }
  };

  if (isLoaded && !isSignedIn) {
    return (
      <div className="app-shell">
        <Header />
        <section className="page-container py-24">
          <div className="mx-auto max-w-[560px] rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-[var(--shadow-card)]">
            <h1 className="text-[40px] font-bold tracking-[-0.05em] text-slate-900">Sign in required</h1>
            <p className="mt-4 text-[16px] leading-relaxed text-slate-600">Please sign in to view your uploaded files and translation history.</p>
            <div className="mt-8">
              <SignInButton mode="modal">
                <button className="rounded-lg bg-slate-900 px-4 py-2 text-[13px] font-semibold text-white">Sign in</button>
              </SignInButton>
            </div>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Header />

      <main className="page-container pb-14 pt-10 sm:pb-20 sm:pt-14">
        <h1 className="text-[48px] font-bold tracking-[-0.03em] text-slate-900">My Files</h1>
        <p className="mt-2 text-[17px] text-slate-600">Access and manage your translated documents</p>

        <section className="mt-8 grid gap-4 md:grid-cols-3">
          {[
            { label: 'Total documents', value: stats.total },
            { label: 'Completed', value: stats.completed },
            { label: 'In progress', value: stats.inProgress },
          ].map((item) => (
            <div key={item.label} className="rounded-2xl border border-slate-200 bg-white p-6">
              <p className="text-[14px] text-slate-500">{item.label}</p>
              <p className="mt-2 text-[32px] font-bold tracking-[-0.03em] text-slate-900">{item.value}</p>
            </div>
          ))}
        </section>

        <section className="mt-6 flex flex-col gap-4 lg:flex-row">
          <div className="flex h-12 flex-1 items-center rounded-xl border border-slate-200 bg-white px-4">
            <Search className="size-4 text-slate-400" strokeWidth={2} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search files..."
              className="ml-3 w-full border-0 bg-transparent text-[14px] text-slate-900 outline-none placeholder:text-slate-400"
            />
          </div>

          <button
            type="button"
            onClick={() => router.push('/')}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-700 px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-slate-800"
          >
            <Upload className="size-4" strokeWidth={2} />
            New translation
          </button>
        </section>

        <section className="mt-5">
          {isLoading ? (
            <div className="rounded-2xl border border-slate-200 bg-white p-16 text-center">
              <Loader2 className="mx-auto size-8 animate-spin text-emerald-600" strokeWidth={2} />
              <p className="mt-4 text-[16px] text-slate-600">Loading your files...</p>
            </div>
          ) : error ? (
            <div className="rounded-2xl border border-slate-200 bg-white p-16 text-center">
              <p className="text-[16px] font-medium text-red-600">{error}</p>
              <button
                type="button"
                onClick={loadFiles}
                className="mt-6 rounded-lg bg-slate-900 px-4 py-2 text-[13px] font-semibold text-white"
              >
                Retry
              </button>
            </div>
          ) : paginatedFiles.length === 0 ? (
            <div className="rounded-2xl border border-slate-200 bg-white p-16 text-center">
              <h2 className="text-[28px] font-bold tracking-[-0.03em] text-slate-900">No files found</h2>
              <p className="mt-4 text-[16px] leading-7 text-slate-600">Upload a PDF to start your first translation.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {paginatedFiles.map((file) => (
                <div
                  key={file.id}
                  className={`group flex cursor-pointer items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white px-4 py-4 transition-all ${
                    file.status === 'completed'
                      ? 'hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md'
                      : 'hover:border-slate-300 hover:bg-slate-50/40'
                  }`}
                  onClick={() => openFile(file)}
                >
                  <div className="flex min-w-0 flex-1 items-center gap-4">
                    <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-slate-700 text-white">
                      <FileText className="size-5" strokeWidth={2} />
                    </div>
                    <div className="min-w-0">
                      <h3 className="truncate text-[17px] font-semibold text-slate-900">{file.original_filename}</h3>
                      <div className="mt-1 flex flex-wrap items-center gap-3 text-[13px] text-slate-500">
                        <span>{formatLanguageLabel(file)}</span>
                        <span>-</span>
                        <span>{file.total_pages} pages</span>
                        <span>-</span>
                        <span>{formatFileSize(file.file_size)}</span>
                        <span>-</span>
                        <span>{formatRelativeTime(file.created_at)}</span>
                      </div>
                      {file.status === 'error' && file.error && (
                        <p className="mt-2 text-[13px] font-medium text-red-600">{file.error}</p>
                      )}
                    </div>
                  </div>

                  <div className="flex shrink-0 items-center gap-4">
                    <StatusPill file={file} />
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        setFileToDelete(file);
                      }}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-300 transition-colors hover:bg-slate-100 hover:text-red-600"
                      aria-label={`Delete ${file.original_filename}`}
                    >
                      <Trash2 className="size-4" strokeWidth={2} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <div className="mt-8 flex flex-col gap-4 text-[14px] text-slate-500 sm:flex-row sm:items-center sm:justify-between">
          <p>
            Showing {filteredFiles.length === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1} to{' '}
            {Math.min(currentPage * PAGE_SIZE, filteredFiles.length)} of {filteredFiles.length} files
          </p>
          <Pagination currentPage={currentPage} totalPages={totalPages} onChange={setCurrentPage} />
        </div>
      </main>

      <DeleteModal
        file={fileToDelete}
        isDeleting={isDeleting}
        onCancel={() => {
          if (!isDeleting) {
            setFileToDelete(null);
          }
        }}
        onConfirm={handleDelete}
      />
    </div>
  );
}

export default function DashboardPage() {
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return <ClerkSetupRequired />;
  }

  return <DashboardContent />;
}
