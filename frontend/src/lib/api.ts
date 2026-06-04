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

async function parseJsonResponse<T>(response: Response, fallbackMessage: string): Promise<T> {
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.detail || fallbackMessage);
  }

  return data;
}

export async function uploadFile(file: File, token?: string | null): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE_URL}/api/upload`, {
    method: 'POST',
    headers: buildAuthHeaders(token),
    body: formData,
  });

  return parseJsonResponse<UploadResponse>(response, 'Failed to upload file');
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

  return parseJsonResponse<TranslationResponse>(response, 'Failed to start translation');
}

export async function getTranslationProgress(
  taskId: string,
  token?: string | null
): Promise<TranslationProgress> {
  const response = await fetch(`${API_BASE_URL}/api/translate/${taskId}/progress`, {
    headers: buildAuthHeaders(token),
  });
  return parseJsonResponse<TranslationProgress>(response, 'Failed to get translation progress');
}

export async function getTranslationResult(
  taskId: string,
  token?: string | null
): Promise<TranslationResult> {
  const response = await fetch(`${API_BASE_URL}/api/translate/${taskId}/result`, {
    headers: buildAuthHeaders(token),
  });
  return parseJsonResponse<TranslationResult>(response, 'Failed to get translation result');
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

  return parseJsonResponse<MyFilesResponse>(response, 'Failed to load files');
}
