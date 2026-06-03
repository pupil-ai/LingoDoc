'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth, SignInButton } from '@clerk/nextjs';
import { useRouter } from 'next/navigation';
import { Header } from '@/components/Header';
import { getMyFiles } from '@/lib/api';
import type { MyFileRecord } from '@/types';

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('en', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

function statusClass(status: MyFileRecord['status']) {
  if (status === 'completed') return 'bg-green-50 text-green-700 border-green-100';
  if (status === 'processing') return 'bg-blue-50 text-blue-700 border-blue-100';
  if (status === 'error') return 'bg-red-50 text-red-700 border-red-100';
  return 'bg-gray-50 text-gray-600 border-gray-100';
}

function DashboardSetupRequired() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-cyan-50">
      <Header />
      <section className="max-w-xl mx-auto px-4 py-24">
        <div className="bg-white/80 backdrop-blur-sm rounded-3xl p-8 shadow-xl border border-white/50 text-center">
          <h1 className="font-display text-3xl font-bold text-gray-900 mb-3">Clerk setup required</h1>
          <p className="text-gray-600">
            Add your Clerk publishable key to <span className="font-mono">frontend/.env.local</span> before using dashboard.
          </p>
        </div>
      </section>
    </div>
  );
}

function DashboardContent() {
  const router = useRouter();
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [files, setFiles] = useState<MyFileRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  const loadFiles = useCallback(async () => {
    if (!isLoaded || !isSignedIn) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      const token = await getToken();
      const response = await getMyFiles(token);
      if (response.success) {
        setFiles(response.files);
      } else {
        setError('Failed to load your files.');
      }
    } catch {
      setError('Failed to load your files.');
    } finally {
      setIsLoading(false);
    }
  }, [getToken, isLoaded, isSignedIn]);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  const openFile = (file: MyFileRecord) => {
    const params = new URLSearchParams({
      fileId: file.id,
      filename: file.original_filename,
      sourceLang: file.source_lang || 'en',
      targetLang: file.target_lang || 'zh',
    });

    if (file.task_id) {
      params.set('taskId', file.task_id);
    }

    router.push(`/translate?${params.toString()}`);
  };

  if (isLoaded && !isSignedIn) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-cyan-50">
        <Header />
        <section className="max-w-xl mx-auto px-4 py-24">
          <div className="bg-white/80 backdrop-blur-sm rounded-3xl p-8 shadow-xl border border-white/50 text-center">
            <h1 className="font-display text-3xl font-bold text-gray-900 mb-3">Sign in required</h1>
            <p className="text-gray-600 mb-6">Please sign in to view your uploaded files and translation history.</p>
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

      <section className="max-w-6xl mx-auto px-4 py-10">
        <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h1 className="font-display text-3xl font-bold text-gray-900">My Files</h1>
            <p className="mt-2 text-gray-600">View uploaded documents, translation status, and previous results.</p>
          </div>
          <button
            onClick={() => router.push('/')}
            className="px-5 py-2 gradient-primary text-white font-medium rounded-xl hover:opacity-90 transition-opacity"
          >
            Upload New File
          </button>
        </div>

        <div className="bg-white/80 backdrop-blur-sm rounded-3xl shadow-xl border border-white/60 overflow-hidden">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-20">
              <div className="mb-4 h-10 w-10 rounded-full border-4 border-primary-100 border-t-primary-500 animate-spin" />
              <p className="text-gray-600">Loading your files...</p>
            </div>
          ) : error ? (
            <div className="py-16 text-center">
              <p className="mb-4 text-red-500">{error}</p>
              <button onClick={loadFiles} className="px-5 py-2 rounded-xl border border-primary-200 text-primary-600 hover:bg-primary-50">
                Retry
              </button>
            </div>
          ) : files.length === 0 ? (
            <div className="py-20 text-center">
              <h2 className="text-xl font-semibold text-gray-800">No files yet</h2>
              <p className="mt-2 text-gray-500">Upload a PDF to start your first translation.</p>
              <button
                onClick={() => router.push('/')}
                className="mt-6 px-5 py-2 gradient-primary text-white font-medium rounded-xl hover:opacity-90 transition-opacity"
              >
                Upload PDF
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-100">
                <thead className="bg-gray-50/80">
                  <tr>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">File</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Pages</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Translation</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Status</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">Uploaded</th>
                    <th className="px-6 py-4 text-right text-xs font-semibold uppercase tracking-wider text-gray-500">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white/70">
                  {files.map((file) => (
                    <tr key={file.id} className="hover:bg-primary-50/40 transition-colors">
                      <td className="px-6 py-4">
                        <div className="max-w-sm">
                          <p className="font-medium text-gray-900 truncate">{file.original_filename}</p>
                          <p className="mt-1 text-xs text-gray-500">{formatFileSize(file.file_size)}</p>
                        </div>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-600">{file.total_pages}</td>
                      <td className="px-6 py-4 text-sm text-gray-600">
                        {file.source_lang && file.target_lang ? `${file.source_lang} → ${file.target_lang}` : 'Not started'}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${statusClass(file.status)}`}>
                          {file.status || 'uploaded'}
                        </span>
                        {file.status === 'processing' && (
                          <p className="mt-2 text-xs text-gray-500">{Math.round(file.progress || 0)}%</p>
                        )}
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-600">{formatDate(file.created_at)}</td>
                      <td className="px-6 py-4 text-right">
                        <button
                          onClick={() => openFile(file)}
                          className="px-4 py-2 rounded-lg border border-primary-200 text-sm font-medium text-primary-600 hover:bg-primary-50 transition-colors"
                        >
                          {file.task_id ? 'Open' : 'Translate'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

export default function DashboardPage() {
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return <DashboardSetupRequired />;
  }

  return <DashboardContent />;
}
