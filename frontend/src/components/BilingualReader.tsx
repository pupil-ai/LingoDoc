'use client';

import { useState } from 'react';

interface BilingualReaderProps {
  taskId: string;
  fileId: string;
}

type DownloadType = 'bilingual' | 'translated';

export function BilingualReader({ taskId, fileId }: BilingualReaderProps) {
  const [downloadingType, setDownloadingType] = useState<DownloadType | null>(null);
  const [previewVersion] = useState(() => Date.now().toString());
  const bilingualFileUrl = `/api/export/${taskId}?format=pdf&output_type=bilingual&v=${previewVersion}`;

  const handleDownload = async (downloadType: DownloadType) => {
    if (downloadingType) {
      return;
    }

    setDownloadingType(downloadType);
    try {
      const downloadUrl = `/api/export/${taskId}?format=pdf&output_type=${downloadType}&download=true&v=${Date.now()}`;
      const response = await fetch(downloadUrl, { cache: 'no-store' });
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
        <div className="h-[800px] overflow-auto">
          <iframe
            src={bilingualFileUrl}
            className="w-full h-full"
            title="Bilingual File Preview"
          />
        </div>
      </div>
    </div>
  );
}
