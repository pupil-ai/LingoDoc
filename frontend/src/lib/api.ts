import type {
  UploadResponse,
  TranslationRequest,
  TranslationResponse,
  TranslationProgress,
  TranslationResult,
  MyFilesResponse,
} from '@/types';

const API_BASE_URL = 'http://localhost:8000';

function buildAuthHeaders(token?: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function uploadFile(file: File, token?: string | null): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE_URL}/api/upload`, {
    method: 'POST',
    headers: buildAuthHeaders(token),
    body: formData,
  });

  return response.json();
}

export async function startTranslation(
  request: TranslationRequest,
  token?: string | null
): Promise<TranslationResponse> {
  const response = await fetch(`${API_BASE_URL}/api/translate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...buildAuthHeaders(token),
    },
    body: JSON.stringify(request),
  });

  return response.json();
}

export async function getTranslationProgress(
  taskId: string,
  token?: string | null
): Promise<TranslationProgress> {
  const response = await fetch(`${API_BASE_URL}/api/translate/${taskId}/progress`, {
    headers: buildAuthHeaders(token),
  });
  return response.json();
}

export async function getTranslationResult(
  taskId: string,
  token?: string | null
): Promise<TranslationResult> {
  const response = await fetch(`${API_BASE_URL}/api/translate/${taskId}/result`, {
    headers: buildAuthHeaders(token),
  });
  return response.json();
}

export async function exportTranslation(
  taskId: string,
  format: 'pdf_bilingual' | 'pdf_translated' | 'text',
  token?: string | null
): Promise<Blob> {
  const params =
    format === 'pdf_bilingual'
      ? 'format=pdf&output_type=bilingual&download=true'
      : format === 'pdf_translated'
        ? 'format=pdf&output_type=translated&download=true'
        : 'format=text';

  const response = await fetch(
    `${API_BASE_URL}/api/export/${taskId}?${params}&v=${Date.now()}`,
    {
      cache: 'no-store',
      headers: buildAuthHeaders(token),
    }
  );
  return response.blob();
}

export async function getMyFiles(token?: string | null): Promise<MyFilesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/my/files`, {
    headers: buildAuthHeaders(token),
    cache: 'no-store',
  });

  return response.json();
}
