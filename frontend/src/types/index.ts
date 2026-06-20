export interface UploadResponse {
  success: boolean;
  fileId: string;
  filename: string;
  totalPages: number;
  fileSize: number;
}

export interface TranslationRequest {
  fileId: string;
  sourceLang: string;
  targetLang: string;
}

export interface TranslationResponse {
  success: boolean;
  taskId: string;
  requestedPages?: number;
  totalPages?: number;
  isPartial?: boolean;
  plan?: string;
  monthlyPageQuota?: number;
  remainingPages?: number | null;
}

export interface TranslationProgress {
  status: 'processing' | 'completed' | 'error' | 'recoverable';
  progress: number;
  processedPages: number;
  totalPages: number;
  requestedPages?: number;
  translatedPages?: number;
  isPartial?: boolean;
  error?: string;
}

export interface TextBlock {
  bbox: { x0: number; y0: number; x1: number; y1: number };
  text: string;
  translatedText: string;
}

export interface PageResult {
  pageNum: number;
  original: string;
  translated: string;
  textBlocks: TextBlock[];
}

export interface TranslationResult {
  success: boolean;
  pages?: PageResult[];
  fileId?: string;
  previewUrl?: string;
  totalPages?: number;
  translatedPages?: number;
  isPartial?: boolean;
  plan?: string;
  pageLimit?: number;
  usageMonth?: string;
  monthlyPageQuota?: number;
}

export interface ExportJobResponse {
  success: boolean;
  status: 'missing' | 'queued' | 'rendering' | 'ready' | 'error';
  taskId: string;
  outputType: 'translated' | 'bilingual';
  downloadUrl?: string;
  elapsedMs?: number;
  sourceBytes?: number;
  exportBytes?: number;
  sizeRatio?: number;
  sizeWarnRatio?: number;
  sizeWarning?: boolean;
  error?: string;
}

export interface MyFileRecord {
  id: string;
  original_filename: string;
  file_size: number;
  total_pages: number;
  storage_provider: string;
  storage_key: string;
  created_at: string;
  task_id: string | null;
  source_lang: string | null;
  target_lang: string | null;
  status: 'processing' | 'completed' | 'error' | null;
  progress: number | null;
  processed_pages: number | null;
  task_total_pages: number | null;
  requested_pages: number | null;
  translated_pages: number | null;
  is_partial: number | null;
  error: string | null;
  task_created_at: string | null;
  task_updated_at: string | null;
}

export interface MyFilesResponse {
  success: boolean;
  files: MyFileRecord[];
}

export interface DeleteFileResponse {
  success: boolean;
  fileId: string;
}

export interface UsageResponse {
  success: boolean;
  plan: string;
  usageMonth: string;
  usedPages: number;
  monthlyPageQuota: number;
  remainingPages: number | null;
  maxPagesPerFile: number;
  maxFileSizeMB: number;
  freePreviewPages: number;
}

export interface LanguageOption {
  code: string;
  name: string;
}

export const SUPPORTED_LANGUAGES: LanguageOption[] = [
  { code: 'en', name: 'English (English)' },
  { code: 'zh', name: 'Chinese (中文)' },
  { code: 'ja', name: 'Japanese (日本語)' },
  { code: 'ko', name: 'Korean (한국어)' },
  { code: 'fr', name: 'French (Français)' },
  { code: 'es', name: 'Spanish (Español)' },
  { code: 'it', name: 'Italian (Italiano)' },
  { code: 'pt', name: 'Portuguese (Português)' },
];

export const SUPPORTED_LANGUAGE_CODES = SUPPORTED_LANGUAGES.map((language) => language.code);

export const SUPPORTED_LANGUAGE_LABELS = SUPPORTED_LANGUAGES.reduce<Record<string, string>>((labels, language) => {
  labels[language.code] = language.name;
  return labels;
}, {});
