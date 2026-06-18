# AGENTS.md

## Project Overview

LingoDoc is a stable PDF translation web app with a Next.js frontend and a FastAPI backend. Users sign in with Clerk, upload PDFs, translate them page by page, preview translated pages in the browser, and export either bilingual side-by-side PDFs or translation-only PDFs.

The current implementation is no longer just an early PDF rendering experiment. It includes real authentication, per-user file history, plan-based limits, monthly page usage tracking, Paddle subscription webhooks, local or Cloudflare R2 storage, page-level translation results, cached export jobs, and basic PDF export quality reporting.

## Current Architecture

- `frontend/` is a Next.js App Router app using Clerk for auth, Paddle.js for checkout, Tailwind CSS, lucide-react icons, and client-side API helpers in `frontend/src/lib/api.ts`.
- `backend/` is a FastAPI app. `backend/main.py` loads `backend/.env`, registers CORS middleware, and includes `backend/app/api/routes.py`.
- `backend/app/api/auth.py` verifies Clerk JWTs with JWKS and provides required/optional current-user dependencies.
- `backend/app/api/routes.py` owns API orchestration: upload, file listing/deletion, usage summary, translation task lifecycle, page previews, export jobs, export downloads, signed preview/download URLs, and Paddle webhooks.
- `backend/app/services/plan_service.py` is the source of truth for plan limits and default quotas.
- `backend/app/services/db_service.py` stores users, files, translation tasks, per-page task state, usage events, and Paddle webhook de-duplication in SQLite.
- `backend/app/services/storage_service.py` abstracts storage. `STORAGE_PROVIDER=local` stores under `LOCAL_STORAGE_ROOT` or `backend/`; `STORAGE_PROVIDER=r2` stores in Cloudflare R2 and keeps a local cache.
- `backend/app/services/translate_service.py` defines translation providers. The production translation path currently selects OfoxAI and chooses model by plan.
- `backend/app/services/pdf_layout_analyzer.py` extracts and classifies PDF text/layout blocks.
- `backend/app/services/pdf_service.py` renders original previews, translated page previews, translated PDFs, bilingual PDFs, page-level JSON results, cached exports, and export quality reports.
- `backend/app/services/pdf_quality_service.py` scans translated output metadata for suspicious translation/export issues.
- `backend/Dockerfile` defines the backend runtime image used for local production-like development and production image deployment.
- `docker-compose.yml` runs the local backend container. It maps host `localhost:18000` to container port `8000` because Windows may reserve host port `8000`.

## Implemented Product Behavior

- Upload requires authentication and accepts only PDFs by filename/content type plus `%PDF` header validation.
- Uploaded file size is enforced server-side from the user's plan.
- Page count is read from the uploaded PDF and stored with the file record.
- Starting translation requires ownership of the uploaded file.
- Free users get monthly preview-page quota and only the first configured pages per PDF are translated.
- Paid users are blocked when a PDF exceeds their per-file page limit or their remaining monthly page quota.
- Usage is reserved per translated page and released if that page ultimately fails.
- Translation task state is persisted in SQLite and mirrored in an in-memory runtime map while active.
- Recoverable/resumable tasks can be restarted for the same file/language pair.
- Page translation results are saved independently, so previews can render from page-level JSON.
- The frontend normally requests result metadata without loading all page JSON.
- Page preview images are rendered from cached exports when available, otherwise directly from page-level translation results.
- Full PDF exports are explicit jobs with status polling. Downloads require a ready cached export.
- Export URLs can be accessed with auth or short-lived signed query parameters.
- Dashboard history lists user files and latest translation task status, and can delete files plus related outputs.
- Paddle webhooks update user plan/subscription status and ignore duplicate webhook events.

## Plan Limits

Plan limits are implemented in code, not only displayed on the pricing page. Defaults in `backend/app/services/plan_service.py` currently match the pricing UI:

- Free: 20 preview pages/month, first 3 pages per PDF, PDF up to 25 MB.
- Starter: 100 pages/month, up to 50 pages per PDF, PDF up to 50 MB.
- Pro: 500 pages/month, up to 300 pages per PDF, PDF up to 100 MB.
- Power: 3,000 pages/month, up to 3,000 pages per PDF, PDF up to 250 MB.

These values can be overridden with env vars such as `FREE_MAX_PAGES_PER_FILE`, `FREE_MAX_FILE_SIZE_MB`, `FREE_MONTHLY_PAGE_QUOTA`, `FREE_PREVIEW_PAGE_LIMIT`, `STARTER_MAX_PAGES_PER_FILE`, `PRO_MONTHLY_PAGE_QUOTA`, and `POWER_MAX_FILE_SIZE_MB`.

If pricing copy changes, update both:

- `frontend/src/app/(site)/pricing/page.tsx`
- `backend/app/services/plan_service.py`

Do not rely on frontend-only checks for billing or quota enforcement.

## PDF Pipeline Notes

- Keep PDF behavior generic. Do not hardcode fixes for one PDF, title, author, emoji, symbol, or sample document.
- Preserve original page appearance as closely as practical.
- Bilingual exports place the original page on the left and translated rendering on the right.
- The original side should remain visually faithful and text-selectable where the source PDF supports it.
- The translated side must not copy the source PDF text layer underneath translated text.
- Images, formulas, decorative marks, dense references, vertical text, and metadata-like regions should generally be preserved or skipped rather than translated as normal prose.
- Translation should operate on layout-aware blocks, not whole pages as one blob.
- Translated block rendering should preserve approximate position, size, color, alignment, boldness, and spacing.
- Prefer readable wrapping and bounded fallback behavior over extreme font shrinking.
- Page-level preview must remain independent from full PDF export. Do not make first preview depend on generating a complete PDF.
- Keep export caching and page-result caching intact when refactoring rendering.
- Be careful with selection behavior: visually hidden text in PDFs can still be selectable.
- Translated PDF rendering must use explicitly configured CJK-capable fonts through `PDF_TRANSLATION_FONT_REGULAR` and `PDF_TRANSLATION_FONT_BOLD`.
- Do not add silent font fallbacks to host Windows/macOS/Linux system fonts for translated output. Missing or unregistrable translation fonts should fail fast so local Docker, staging, and production surface the problem before bad PDFs are generated.

## Translation Rules

- Do not add explanations, notes, glosses, or parenthetical original terms unless they already exist in the source.
- Do not add artificial line breaks inside a paragraph.
- Preserve layout markers such as bullets, numbering, emoji, leading symbols, citations, and reference markers.
- Keep proper nouns, brand names, product names, and common technical terms in their original form when appropriate.
- Preserve placeholder/reference tokens exactly when the translation batching code introduces them.
- Do not merge adjacent blocks, split one block into unrelated blocks, or move content between blocks.

## Important Environment Variables

Backend:

- `CLERK_ISSUER_URL`, optional `CLERK_JWKS_URL`, optional `CLERK_JWT_AUDIENCE`
- `OFOXAI_API_KEY`, optional `OFOXAI_BASE_URL`, `OFOXAI_FREE_MODEL`, `OFOXAI_SUBSCRIPTION_MODEL`
- `PADDLE_WEBHOOK_SECRET`, optional `PADDLE_WEBHOOK_TOLERANCE_SECONDS`
- `PREVIEW_URL_SECRET` for signed preview/download URLs
- `DATABASE_PATH`
- `STORAGE_PROVIDER` as `local` or `r2`
- `LOCAL_STORAGE_ROOT`, `LOCAL_STORAGE_CACHE_DIR`
- `R2_BUCKET`, `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`
- `TRANSLATION_BATCH_MAX_BLOCKS`, `TRANSLATION_BATCH_MAX_CHARS`, `TRANSLATION_BATCH_CONCURRENCY`
- `TRANSLATION_FALLBACK_CONCURRENCY`, `PAGE_TRANSLATION_CONCURRENCY`, `PAGE_RETRY_LIMIT`
- `AUTO_PREPARE_EXPORTS`, `AUTO_PREPARE_EXPORT_TYPES`
- `PDF_PERF_LOGS`
- `PDF_TRANSLATION_FONT_REGULAR`, `PDF_TRANSLATION_FONT_BOLD`
- plan limit env vars listed above

Frontend:

- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
- `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN`
- `NEXT_PUBLIC_PADDLE_ENVIRONMENT`
- `NEXT_PUBLIC_PADDLE_STARTER_MONTHLY_PRICE_ID`, `NEXT_PUBLIC_PADDLE_STARTER_YEARLY_PRICE_ID`
- `NEXT_PUBLIC_PADDLE_PRO_MONTHLY_PRICE_ID`, `NEXT_PUBLIC_PADDLE_PRO_YEARLY_PRICE_ID`
- `NEXT_PUBLIC_PADDLE_POWER_MONTHLY_PRICE_ID`, `NEXT_PUBLIC_PADDLE_POWER_YEARLY_PRICE_ID`

Do not commit real secrets or production `.env` files.

## Development Commands

Backend:

```powershell
docker compose up --build backend
```

The local Docker backend is exposed at `http://localhost:18000`; the container still listens on port `8000`.

Use the Docker backend for normal local development and production-parity checks. `python main.py` is only for narrow debugging when explicitly needed, and it must still use the same explicit translation font environment variables. Do not treat host Python as a production-equivalent validation path.

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Validation:

```powershell
python -m py_compile backend/app/services/pdf_service.py backend/app/api/routes.py backend/app/services/translate_service.py
docker compose build backend
cd frontend
npx.cmd tsc --noEmit
npm run build
```

## Deployment Notes

- `backend/main.py` currently allows `allow_origins=["*"]`; lock this down for production domains before public launch.
- `frontend/next.config.js` rewrites `/api/*` to `http://localhost:18000/api/*` by default for local Docker development. Production should set `NEXT_PUBLIC_API_BASE_URL` or use platform routing intentionally.
- Use `PREVIEW_URL_SECRET` in production instead of relying on fallback secrets.
- Production backend deployment should run an immutable backend Docker image built from `backend/Dockerfile`; do not deploy production by running `git pull`, `pip install`, and bare `python main.py` on the server.
- `scripts/deploy-lingodoc-backend` is the deployment script template. It expects an image reference, starts the backend container, verifies PDF translation fonts inside the container, health-checks the API, and rolls back on failure.
- Keep development and production as separate environments with separate `.env`, storage, database, and secrets. They should share the same Dockerfile/runtime shape and font strategy, not the same live instance or data.
- R2 is supported, but local storage is easier for development.
- SQLite is currently the database. If running multiple backend instances, consider that in-memory `translation_tasks` and `export_tasks` are process-local while persisted task/file/user state is in SQLite/storage.
- Background work uses FastAPI background tasks and in-process asyncio. Large production deployments may need a real queue/worker model before horizontal scaling.
- Export downloads are intentionally blocked with `409` until an export job has produced a cached PDF.
- Clean up uploaded files, page JSON, cached exports, local R2 cache, and SQLite backups according to the deployment retention policy.

## Validation Before PDF-Related Changes

- Run `python -m py_compile backend/app/services/pdf_service.py backend/app/api/routes.py backend/app/services/translate_service.py`.
- Build and start the backend Docker container with `docker compose up --build backend` when validating PDF rendering or deployment-parity behavior.
- If frontend code changes, run `npx.cmd tsc --noEmit` from `frontend`.
- For UI-affecting frontend changes, also run `npm run build` from `frontend` when feasible.
- Upload a real PDF, translate it, preview translated pages, start export jobs for `bilingual` and `translated`, and download both PDFs.
- Inspect at least one multi-page PDF. When fixtures are available, also test a multi-column academic PDF, a document with headers/footers, and a document with figures/tables.
- Check that free/paid plan limits still behave as expected after changes touching upload, translation, usage, or billing code.
- On Windows, do not pipe inline scripts containing raw CJK or other non-ASCII test text through PowerShell. Use Unicode escapes, a UTF-8 file, or another encoding-safe path.

## Safety

- Do not commit changes unless the user explicitly asks.
- Do not add secrets, API keys, tokens, private credentials, uploaded PDFs, generated exports, SQLite databases, or log files to the repository.
- Keep changes focused on the requested task and avoid unrelated refactors.
- Preserve user-owned files and dirty worktree changes.
- Treat `docs/` and `design/` as user-owned reference/work-in-progress folders. Do not read, edit, summarize, reformat, or use files under those folders unless the user explicitly asks to reference or modify them.
- Prefer small, verifiable changes over broad rewrites unless the user asks for a refactor.
