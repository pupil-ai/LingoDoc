# LingoDoc

LingoDoc is a PDF translation web app for authenticated users. It uploads PDFs, translates document pages with a layout-aware pipeline, previews translated pages in the browser, and exports either bilingual side-by-side PDFs or translation-only PDFs.

## Current Status

This repository is a stable product version, not only an early PDF rendering prototype. The current app includes:

- Clerk authentication for upload, translation, history, preview, and download APIs.
- Paddle checkout and subscription webhooks.
- Server-side plan limits for file size, pages per PDF, and monthly translated pages.
- SQLite persistence for users, uploaded files, translation tasks, page task state, usage, and webhook de-duplication.
- Local storage and Cloudflare R2 storage support.
- Page-level translation results and page-level preview rendering.
- Explicit export jobs for bilingual and translation-only PDFs.
- Cached PDF exports and export quality metadata.
- A dashboard for file history and deletion.

## Repository Layout

```text
backend/
  main.py
  app/api/
    auth.py
    routes.py
  app/services/
    db_service.py
    pdf_layout_analyzer.py
    pdf_service.py
    pdf_quality_service.py
    plan_service.py
    storage_service.py
    translate_service.py

frontend/
  src/app/
    (site)/page.tsx
    (site)/pricing/page.tsx
    (site)/dashboard/page.tsx
    translate/page.tsx
  src/components/
  src/lib/api.ts
  src/types/index.ts

docs/
  issues.md
  memo .md
```

## How The App Works

1. A signed-in user uploads a PDF from the home page.
2. The backend validates that the upload is a PDF, checks the user's plan file-size limit, stores the file, reads the page count, and records it in SQLite.
3. The user opens the translation workspace, chooses source/target languages, and starts translation.
4. The backend checks ownership, plan page limits, and remaining monthly quota.
5. Translation runs page by page. Each page gets its own task row, retry state, usage reservation, and page-level JSON result.
6. The frontend polls progress and loads result metadata without fetching all translated pages.
7. Page previews are rendered from cached exports when available, or from page-level translation JSON otherwise.
8. PDF download starts an export job and polls until the cached export is ready.
9. The dashboard shows uploaded files and latest task status, and can delete a file plus related outputs.

## Plans And Limits

Plan limits are enforced in the backend, not only displayed in the pricing UI.

Defaults:

| Plan | Monthly quota | Per-PDF page limit | File size limit |
| --- | ---: | ---: | ---: |
| Free | 20 preview pages | First 3 pages translated | 25 MB |
| Starter | 100 pages | 50 pages | 50 MB |
| Pro | 500 pages | 300 pages | 100 MB |
| Power | 3,000 pages | 3,000 pages | 250 MB |

Backend source of truth:

- `backend/app/services/plan_service.py`

Pricing UI copy:

- `frontend/src/app/(site)/pricing/page.tsx`

Keep both in sync when changing product packaging.

## Backend Setup

```powershell
cd backend
python -m pip install -r requirements.txt
python main.py
```

The backend reads environment variables from `backend/.env`.

Important backend variables:

- `CLERK_ISSUER_URL`
- `OFOXAI_API_KEY`
- `PADDLE_WEBHOOK_SECRET`
- `PREVIEW_URL_SECRET`
- `DATABASE_PATH`
- `STORAGE_PROVIDER`
- `LOCAL_STORAGE_ROOT`
- `R2_BUCKET`
- `R2_ENDPOINT_URL`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `TRANSLATION_BATCH_MAX_BLOCKS`
- `TRANSLATION_BATCH_MAX_CHARS`
- `TRANSLATION_BATCH_CONCURRENCY`
- `PAGE_TRANSLATION_CONCURRENCY`
- `PAGE_RETRY_LIMIT`
- plan limit override variables such as `FREE_MAX_FILE_SIZE_MB` and `PRO_MONTHLY_PAGE_QUOTA`

## Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```

Important frontend variables:

- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
- `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN`
- `NEXT_PUBLIC_PADDLE_ENVIRONMENT`
- Paddle price IDs for Starter, Pro, and Power monthly/yearly plans

For local development, `frontend/next.config.js` rewrites `/api/*` to `http://localhost:8000/api/*`. Production should set routing intentionally, usually via `NEXT_PUBLIC_API_BASE_URL` or deployment-platform rewrites.

## Validation

Backend syntax check:

```powershell
python -m py_compile backend/app/services/pdf_service.py backend/app/api/routes.py backend/app/services/translate_service.py
```

Frontend checks:

```powershell
cd frontend
npx.cmd tsc --noEmit
npm run build
```

Manual smoke test before deployment:

- Upload a signed-in PDF.
- Confirm upload rejects non-PDF files and oversized PDFs.
- Translate a file on a free account and confirm partial preview behavior.
- Translate a paid-plan file within its limits.
- Check progress polling and page preview loading.
- Start bilingual and translation-only export jobs.
- Download both PDFs and inspect layout, text selection, and file size.
- Open the dashboard, reopen a completed task, and delete a file.

## Production Notes

- `backend/main.py` currently allows all CORS origins. Restrict this before public launch.
- Use a dedicated `PREVIEW_URL_SECRET` in production.
- Cloudflare R2 is supported for object storage. Local storage is simpler for development.
- SQLite plus in-process background tasks are suitable for simple deployments, but multiple backend instances need extra care because runtime task maps are process-local.
- Large-scale deployment should move translation/export work to a durable queue and worker.
- Do not commit `.env`, uploaded PDFs, generated exports, SQLite databases, or logs.
