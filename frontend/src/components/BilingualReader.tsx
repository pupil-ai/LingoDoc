'use client';

interface BilingualReaderProps {
  taskId: string;
  fileId: string;
}

export function BilingualReader({ taskId, fileId }: BilingualReaderProps) {
  const bilingualPdfUrl = `/api/export/${taskId}?format=pdf&output_type=bilingual`;
  const downloadBilingualUrl = `/api/export/${taskId}?format=pdf&output_type=bilingual&download=true`;

  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h3 className="text-lg font-semibold text-gray-800">Bilingual Translation</h3>
        </div>

        <div className="flex items-center gap-2">
          <a
            href={downloadBilingualUrl}
            download
            className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors text-sm font-medium"
          >
            Download Bilingual PDF
          </a>
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
