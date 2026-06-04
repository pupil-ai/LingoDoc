'use client';

import { useEffect, useRef, useState } from 'react';
import { useAuth } from '@clerk/nextjs';

interface BilingualReaderProps {
  taskId: string;
  fileId: string;
}

type DownloadType = 'bilingual' | 'translated';

export function BilingualReader({ taskId, fileId }: BilingualReaderProps) {
  const { getToken } = useAuth();
  const [downloadingType, setDownloadingType] = useState<DownloadType | null>(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(true);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState('');
  const previewContainerRef = useRef<HTMLDivElement | null>(null);
  const previewFrameRef = useRef<HTMLIFrameElement | null>(null);
  const [previewVersion] = useState(() => Date.now().toString());

  useEffect(() => {
    let objectUrl: string | null = null;
    let isCancelled = false;

    async function loadPreview() {
      setIsPreviewLoading(true);
      setPreviewError('');

      try {
        const token = await getToken({ skipCache: true });
        const response = await fetch(`/api/export/${taskId}?format=pdf&output_type=bilingual&v=${previewVersion}`, {
          cache: 'no-store',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });

        if (!response.ok) {
          throw new Error('Failed to load preview');
        }

        const blob = await response.blob();
        objectUrl = URL.createObjectURL(
          blob.type === 'application/pdf' ? blob : new Blob([blob], { type: 'application/pdf' })
        );

        if (!isCancelled) {
          setPreviewUrl(`${objectUrl}#page=1&zoom=page-fit`);
        }
      } catch {
        if (!isCancelled) {
          setPreviewError('Failed to load file preview. Please try downloading the file instead.');
          setIsPreviewLoading(false);
        }
      }
    }

    loadPreview();

    return () => {
      isCancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [getToken, previewVersion, taskId]);

  const resetPreviewScroll = () => {
    previewContainerRef.current?.scrollTo({ top: 0, left: 0 });

    try {
      previewFrameRef.current?.contentWindow?.scrollTo(0, 0);
    } catch {
      void 0;
    }

    setIsPreviewLoading(false);
  };

  const handleDownload = async (downloadType: DownloadType) => {
    if (downloadingType) {
      return;
    }

    setDownloadingType(downloadType);
    try {
      const downloadUrl = `/api/export/${taskId}?format=pdf&output_type=${downloadType}&download=true&v=${Date.now()}`;
      const token = await getToken({ skipCache: true });
      const response = await fetch(downloadUrl, {
        cache: 'no-store',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) {
        throw new Error('Failed to download file');
      }

      const blob = await response.blob();
      const fileBlob = blob.type === 'application/pdf'
        ? blob
        : new Blob([blob], { type: 'application/pdf' });
      const objectUrl = URL.createObjectURL(fileBlob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = `${taskId}_${downloadType}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } finally {
      setDownloadingType(null);
    }
  };

  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h3 className="text-lg font-semibold text-gray-800">Bilingual Translation</h3>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => handleDownload('translated')}
            disabled={!!downloadingType}
            className="px-4 py-2 bg-white text-primary-600 border border-primary-200 rounded-lg hover:bg-primary-50 transition-colors text-sm font-medium disabled:opacity-50"
          >
            {downloadingType === 'translated' ? 'Downloading...' : 'Download Translated File'}
          </button>
          <button
            type="button"
            onClick={() => handleDownload('bilingual')}
            disabled={!!downloadingType}
            className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors text-sm font-medium"
          >
            {downloadingType === 'bilingual' ? 'Downloading...' : 'Download Bilingual File'}
          </button>
        </div>
      </div>

      <div className="bg-white rounded-2xl shadow-lg overflow-hidden">
        <div ref={previewContainerRef} className="relative h-[800px] overflow-auto bg-slate-100">
          {isPreviewLoading && (
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-white/95 text-center">
              <div className="mb-4 h-10 w-10 rounded-full border-4 border-primary-100 border-t-primary-500 animate-spin" />
              <h3 className="text-lg font-semibold text-gray-800">Loading File Preview</h3>
              <p className="mt-2 text-sm text-gray-500">
                Preparing the document viewer. Large or layout-heavy files may take a moment.
              </p>
            </div>
          )}
          {previewError && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/95 px-6 text-center text-sm font-medium text-red-500">
              {previewError}
            </div>
          )}
          {previewUrl && (
            <iframe
              ref={previewFrameRef}
              key={previewUrl}
              src={previewUrl}
              onLoad={resetPreviewScroll}
              className={`w-full h-full transition-opacity duration-300 ${isPreviewLoading ? 'opacity-0' : 'opacity-100'}`}
              title="Bilingual File Preview"
            />
          )}
        </div>
      </div>
    </div>
  );
}
