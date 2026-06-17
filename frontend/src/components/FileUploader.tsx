'use client';

import type { ChangeEvent, DragEvent } from 'react';
import { useCallback, useRef, useState } from 'react';
import { Loader2, Upload } from 'lucide-react';

interface FileUploaderProps {
  onFileUpload: (file: File) => boolean | void | Promise<boolean | void>;
  disabled?: boolean;
  keepLoadingOnSuccess?: boolean;
  onBlockedUploadAttempt?: () => void;
}

export function FileUploader({
  onFileUpload,
  disabled = false,
  keepLoadingOnSuccess = false,
  onBlockedUploadAttempt,
}: FileUploaderProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState('');

  const handleFile = useCallback(async (file: File) => {
    let uploadSucceeded = false;

    if (disabled || isUploading) {
      return;
    }

    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      setError('Only PDF files are supported.');
      return;
    }

    setError('');
    setIsUploading(true);
    try {
      const result = await onFileUpload(file);
      uploadSucceeded = result !== false;
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : 'An error occurred during upload.');
    } finally {
      if (!uploadSucceeded || !keepLoadingOnSuccess) {
        setIsUploading(false);
      }
    }
  }, [disabled, isUploading, keepLoadingOnSuccess, onFileUpload]);

  const onBrowse = () => {
    if (onBlockedUploadAttempt) {
      onBlockedUploadAttempt();
      return;
    }

    if (!disabled && !isUploading) {
      inputRef.current?.click();
    }
  };

  const handleChange = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) {
      await handleFile(file);
    }
  }, [handleFile]);

  const handleDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (onBlockedUploadAttempt) {
      return;
    }

    if (!disabled && !isUploading) {
      setIsDragging(true);
    }
  }, [disabled, isUploading, onBlockedUploadAttempt]);

  const handleDragLeave = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);

    if (onBlockedUploadAttempt) {
      onBlockedUploadAttempt();
      return;
    }

    const file = event.dataTransfer.files?.[0];
    if (file) {
      await handleFile(file);
    }
  }, [handleFile, onBlockedUploadAttempt]);

  return (
    <div className="w-full max-w-[840px]">
      <div
        role="button"
        tabIndex={0}
        onClick={onBrowse}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            onBrowse();
          }
        }}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`group flex min-h-[262px] cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed px-8 text-center transition-all ${
          isDragging ? 'border-emerald-400 bg-emerald-50/60' : 'border-slate-200 bg-white'
        } ${disabled ? 'cursor-not-allowed opacity-70' : 'hover:border-slate-300'} `}
      >
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-slate-200 bg-white shadow-sm">
          {isUploading ? (
            <Loader2 className="size-6 animate-spin text-emerald-600" strokeWidth={2} />
          ) : (
            <Upload className="size-6 text-slate-400" strokeWidth={2} />
          )}
        </div>

        <p className="mt-5 text-[20px] font-semibold tracking-[-0.03em] text-slate-900">
          {isUploading ? 'Uploading PDF...' : 'Drop a PDF file here'}
        </p>
        <p className="mt-2 text-[16px] text-slate-500">
          or <span className="font-medium text-emerald-600 transition-colors group-hover:text-emerald-700">browse files</span>
        </p>

        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          disabled={disabled || isUploading}
          onChange={handleChange}
        />
      </div>

      {error && <p className="mt-4 text-center text-sm font-medium text-red-600">{error}</p>}
    </div>
  );
}
