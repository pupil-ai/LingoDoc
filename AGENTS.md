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

## Safety

- Do not commit changes unless the user explicitly asks.
- Do not add secrets, API keys, tokens, or private credentials to the repository.
- Keep changes focused on the requested task and avoid unrelated refactors.
