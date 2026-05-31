'use client';

import { useState } from 'react';

interface BilingualReaderProps {
  taskId: string;
  fileId: string;
}

export function BilingualReader({ taskId, fileId }: BilingualReaderProps) {
  const [isDownloading, setIsDownloading] = useState(false);
  const [previewVersion] = useState(() => Date.now().toString());
  const bilingualPdfUrl = `/api/export/${taskId}?format=pdf&output_type=bilingual&v=${previewVersion}`;

  const handleDownload = async () => {
    if (isDownloading) {
      return;
    }

    setIsDownloading(true);
    try {
      const downloadUrl = `/api/export/${taskId}?format=pdf&output_type=bilingual&download=true&v=${Date.now()}`;
      const response = await fetch(downloadUrl, { cache: 'no-store' });
      if (!response.ok) {
        throw new Error('Failed to download bilingual PDF');
      }

      const blob = await response.blob();
      const pdfBlob = blob.type === 'application/pdf'
        ? blob
        : new Blob([blob], { type: 'application/pdf' });
      const objectUrl = URL.createObjectURL(pdfBlob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = `${taskId}_bilingual.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } finally {
      setIsDownloading(false);
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
            onClick={handleDownload}
            disabled={isDownloading}
            className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors text-sm font-medium"
          >
            {isDownloading ? 'Downloading...' : 'Download Bilingual PDF'}
          </button>
        </div>
      </div>

      <div className="bg-white rounded-2xl shadow-lg overflow-hidden">
        <div className="h-[800px] overflow-auto">
          <iframe
            src={bilingualPdfUrl}
            className="w-full h-full"
            title="Bilingual PDF"
          />
        </div>
      </div>
    </div>
  );
}
