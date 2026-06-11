import type {
  DeleteFileResponse,
  ExportJobResponse,
  MyFilesResponse,
  TranslationProgress,
  TranslationRequest,
  TranslationResponse,
  TranslationResult,
  UploadResponse,
  UsageResponse,
} from '@/types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || '';

function resolveApiBaseUrl(): string {
  if (API_BASE_URL) {
    return API_BASE_URL;
  }

  if (typeof window === 'undefined') {
    return '';
  }

  const { hostname, protocol } = window.location;
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return `${protocol}//${hostname}:8000`;
  }

  return '';
}

export function buildUrl(path: string): string {
  return `${resolveApiBaseUrl()}${path}`;
}

function buildAuthHeaders(token?: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseJsonResponse<T>(response: Response, fallbackMessage: string): Promise<T> {
  const rawText = await response.text();
  let data: any = null;

  if (rawText) {
    try {
      data = JSON.parse(rawText);
    } catch {
      if (!response.ok) {
        throw new Error(rawText || fallbackMessage);
      }
      throw new Error(fallbackMessage);
    }
  }

  if (!response.ok) {
    throw new Error(data?.detail || fallbackMessage);
  }

  return data;
}

export async function uploadFile(file: File, token?: string | null): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(buildUrl('/api/upload'), {
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
  const response = await fetch(buildUrl('/api/translate'), {
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
  const response = await fetch(buildUrl(`/api/translate/${taskId}/progress`), {
    headers: buildAuthHeaders(token),
  });
  return parseJsonResponse<TranslationProgress>(response, 'Failed to get translation progress');
}

export async function getTranslationResult(
  taskId: string,
  includePages = true,
  token?: string | null
): Promise<TranslationResult> {
  const response = await fetch(buildUrl(`/api/translate/${taskId}/result?include_pages=${includePages}`), {
    headers: buildAuthHeaders(token),
  });
  return parseJsonResponse<TranslationResult>(response, 'Failed to get translation result');
}

export function buildExportUrl(taskId: string, params: string): string {
  return buildUrl(`/api/export/${taskId}?${params}`);
}

export async function startExportJob(
  taskId: string,
  outputType: 'translated' | 'bilingual',
  token?: string | null
): Promise<ExportJobResponse> {
  const response = await fetch(buildUrl(`/api/export/${taskId}/jobs`), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...buildAuthHeaders(token),
    },
    body: JSON.stringify({ outputType }),
  });

  return parseJsonResponse<ExportJobResponse>(response, 'Failed to start export job');
}

export async function getExportJob(
  taskId: string,
  outputType: 'translated' | 'bilingual',
  token?: string | null
): Promise<ExportJobResponse> {
  const response = await fetch(buildUrl(`/api/export/${taskId}/jobs/${outputType}`), {
    headers: buildAuthHeaders(token),
    cache: 'no-store',
  });

  return parseJsonResponse<ExportJobResponse>(response, 'Failed to get export job status');
}

export async function getOriginalFilePreviewBlob(
  fileId: string,
  token?: string | null,
  page = 1,
  width = 1400
): Promise<Blob> {
  const response = await fetch(buildUrl(`/api/files/${fileId}/preview?page=${page}&width=${width}`), {
    headers: buildAuthHeaders(token),
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new Error('Failed to load original preview image');
  }

  return response.blob();
}

export async function getTranslationPagePreviewBlob(
  taskId: string,
  token?: string | null,
  page = 1,
  width = 1800
): Promise<Blob> {
  const response = await fetch(buildUrl(`/api/translate/${taskId}/pages/${page}/preview?width=${width}`), {
    headers: buildAuthHeaders(token),
    cache: 'force-cache',
  });

  if (!response.ok) {
    throw new Error('Failed to load translated page preview');
  }

  return response.blob();
}

export async function getMyFiles(token?: string | null): Promise<MyFilesResponse> {
  const response = await fetch(buildUrl('/api/my/files'), {
    headers: buildAuthHeaders(token),
    cache: 'no-store',
  });

  return parseJsonResponse<MyFilesResponse>(response, 'Failed to load files');
}

export async function deleteMyFile(fileId: string, token?: string | null): Promise<DeleteFileResponse> {
  const response = await fetch(buildUrl(`/api/my/files/${fileId}`), {
    method: 'DELETE',
    headers: buildAuthHeaders(token),
  });

  return parseJsonResponse<DeleteFileResponse>(response, 'Failed to delete file');
}

export async function getMyUsage(token?: string | null): Promise<UsageResponse> {
  const response = await fetch(buildUrl('/api/me/usage'), {
    headers: buildAuthHeaders(token),
    cache: 'no-store',
  });

  return parseJsonResponse<UsageResponse>(response, 'Failed to load usage');
}
