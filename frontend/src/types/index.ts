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
}

export interface TranslationProgress {
  status: 'processing' | 'completed' | 'error';
  progress: number;
  processedPages: number;
  totalPages: number;
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
  pages: PageResult[];
}

export interface MyFileRecord {
  id: string;
  original_filename: string;
  file_size: number;
  total_pages: number;
  created_at: string;
  task_id: string | null;
  source_lang: string | null;
  target_lang: string | null;
  status: 'processing' | 'completed' | 'error' | null;
  progress: number | null;
  processed_pages: number | null;
  error: string | null;
  task_created_at: string | null;
  task_updated_at: string | null;
}

export interface MyFilesResponse {
  success: boolean;
  files: MyFileRecord[];
}

export interface LanguageOption {
  code: string;
  name: string;
}

export const SUPPORTED_LANGUAGES: LanguageOption[] = [
  { code: 'en', name: 'English' },
  { code: 'zh', name: '中文' },
  { code: 'ja', name: '日本語' },
  { code: 'ko', name: '한국어' },
  { code: 'fr', name: 'Français' },
  { code: 'de', name: 'Deutsch' },
  { code: 'es', name: 'Español' },
  { code: 'ru', name: 'Русский' },
];
