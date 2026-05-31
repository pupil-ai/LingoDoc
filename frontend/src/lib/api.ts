import type {
  UploadResponse,
  TranslationRequest,
  TranslationResponse,
  TranslationProgress,
  TranslationResult,
} from '@/types';

const API_BASE_URL = 'http://localhost:8000';

export async function uploadFile(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE_URL}/api/upload`, {
    method: 'POST',
    body: formData,
  });

  return response.json();
}

export async function startTranslation(
  request: TranslationRequest
): Promise<TranslationResponse> {
  const response = await fetch(`${API_BASE_URL}/api/translate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  return response.json();
}

export async function getTranslationProgress(
  taskId: string
): Promise<TranslationProgress> {
  const response = await fetch(`${API_BASE_URL}/api/translate/${taskId}/progress`);
  return response.json();
}

export async function getTranslationResult(
  taskId: string
): Promise<TranslationResult> {
  const response = await fetch(`${API_BASE_URL}/api/translate/${taskId}/result`);
  return response.json();
}

export async function exportTranslation(
  taskId: string,
  format: 'pdf_bilingual' | 'pdf_translated' | 'text'
): Promise<Blob> {
  const params =
    format === 'pdf_bilingual'
      ? 'format=pdf&output_type=bilingual&download=true'
      : format === 'pdf_translated'
        ? 'format=pdf&output_type=translated&download=true'
        : 'format=text';

  const response = await fetch(
    `${API_BASE_URL}/api/export/${taskId}?${params}`
  );
  return response.blob();
}
