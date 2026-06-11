# AGENTS.md

## Project Overview

LingoDoc is a PDF translation tool. It uploads PDFs, translates text, previews bilingual pages, and exports bilingual PDFs with the original content on the left and translated content on the right.

## Core PDF Requirements

- Do not hardcode behavior for one specific PDF, emoji, heading text, author name, or sample document.
- Preserve the original PDF visual layout as much as possible.
- The left side of bilingual PDFs should keep the original PDF appearance and text selectability.
- The right side should preserve the original visual layout, but it must not keep hidden original text selectable underneath translated text.
- Images, formulas, decorative symbols, and non-text visual elements should not be translated.
- Translated text should follow the source block style as closely as possible: position, size, color, boldness, alignment, and spacing.
- Avoid unlimited font shrinking. Prefer readable text, controlled wrapping, and safe overflow handling.

## Current Refactor Goal

The current priority is to refactor the PDF translation pipeline toward page-based, scalable, approximately faithful rendering instead of patching isolated layout heuristics.

Primary goals:

- PDF output should be approximately faithful to the original layout, with no obvious layout errors, overlaps, blank pages, corrupted text, or mixed paragraphs.
- Translation speed for normal documents with dozens of pages should be acceptable for interactive use; very large documents such as 3000-page PDFs may be long-running asynchronous jobs.
- Preview loading must not depend on generating or downloading the full bilingual PDF.
- Translated pages should become previewable page-by-page as soon as page results are available.
- Full PDF export should be a separate rendering/export job, not the first-preview path.
- Prefer page-level data, page-level rendering, and page-level caching over whole-document blocking work.
- Avoid continuing to add one-off rules to `pdf_service.py` when the underlying problem is missing layout structure or pipeline boundaries.

Architecture direction:

- Separate PDF analysis, layout classification, translation orchestration, page preview rendering, and full PDF export into distinct modules when making substantial changes.
- Build or preserve an intermediate page layout representation before translation.
- Classify text regions before translation: body, title, header, footer, margin, figure, table, formula, decorative, or unknown.
- Translate only appropriate text regions; preserve or skip formulas, decorative symbols, repeated marginalia, and non-content running headers/footers unless explicitly required.
- Use collision-aware layout when placing translated text. Do not allow translated text to overlap adjacent regions.
- Prefer readable text and controlled wrapping over aggressive font shrinking.

Performance direction:

- Use configurable translation concurrency and batching.
- Use translation caches for repeated text blocks.
- Avoid reopening and reparsing the same PDF page multiple times when one pass can collect the needed data.
- Avoid loading huge translation JSON payloads in the frontend.
- Avoid fetching full PDF blobs into frontend memory before download when a streamed or signed download URL can be used.

## PDF Text Layer Notes

- Be careful with PDF selection behavior. Hidden text layers can still be selected even if they are covered visually.
- Do not copy the source PDF as a selectable text layer on the translation side.
- Do not write an entire translated page as one shared text stream if it causes large-range text selection issues.
- Prefer paragraph/block-level text insertion for translated content.
- PDF fixes must be generic for user-uploaded PDFs, not tailored to the current sample document.

## Translation Rules

- Do not add explanations, notes, glosses, or parenthetical original terms unless they already exist in the source text.
- Do not add artificial line breaks inside a paragraph.
- Keep proper nouns, brand names, product names, and common technical terms in their original form when appropriate.
- Preserve layout markers such as bullets, numbering, emoji, and leading symbols when they are part of the source text.

## Validation

Before finishing PDF-related changes:

- Run `python -m py_compile backend/app/services/pdf_service.py backend/app/api/routes.py backend/app/services/translate_service.py`.
- If frontend code changes, run `npx.cmd tsc --noEmit` from `frontend`.
- Generate or export a bilingual PDF and inspect layout, text selection, and downloaded PDF behavior.
- For PDF pipeline refactors, test first preview load time separately from full PDF export time.
- When fixtures are available, test at least one multi-column academic PDF, one document with headers/footers, and one document with figures/tables.
- On Windows, do not pipe inline scripts containing raw CJK or other non-ASCII test text through PowerShell. Use Unicode escapes, a UTF-8 file, or another encoding-safe path so test data is not silently replaced with `?`.

## Safety

- Do not commit changes unless the user explicitly asks.
- Do not add secrets, API keys, tokens, or private credentials to the repository.
- Keep changes focused on the requested task and avoid unrelated refactors.
