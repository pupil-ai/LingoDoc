from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
import json
import os
import re
import sys

import aiohttp


SUPPORTED_LANGUAGE_CODES = [
    "en",
    "zh",
    "ja",
    "ko",
    "es",
    "fr",
    "it",
    "pt",
    "de",
    "nl",
    "pl",
    "ru",
    "uk",
    "fi",
    "tr",
    "vi",
    "id",
    "ms",
]

LANGUAGE_NAMES = {
    "en": "English",
    "zh": "Simplified Chinese (简体中文)",
    "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)",
    "es": "Spanish (Español)",
    "fr": "French (Français)",
    "it": "Italian (Italiano)",
    "pt": "Portuguese (Português)",
    "de": "German (Deutsch)",
    "nl": "Dutch (Nederlands)",
    "pl": "Polish (Polski)",
    "ru": "Russian (Русский)",
    "uk": "Ukrainian (Українська)",
    "fi": "Finnish (Suomi)",
    "tr": "Turkish (Türkçe)",
    "vi": "Vietnamese (Tiếng Việt)",
    "id": "Indonesian (Bahasa Indonesia)",
    "ms": "Malay (Bahasa Melayu)",
}


def _language_name(lang: str) -> str:
    normalized = (lang or "").strip().lower()
    return LANGUAGE_NAMES.get(normalized, lang)


def safe_print(msg: str) -> None:
    """Print safely on Windows terminals that may not support every character."""
    try:
        print(msg)
    except UnicodeEncodeError:
        safe_msg = msg.encode(sys.stdout.encoding, errors="ignore").decode(sys.stdout.encoding)
        print(safe_msg)


class TranslationService(ABC):
    @abstractmethod
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_supported_languages(self) -> List[str]:
        raise NotImplementedError

    async def translate_batch(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        translations: List[str] = []
        for text in texts:
            translations.append(await self.translate(text, source_lang, target_lang))
        return translations

    async def translate_structured_batch(
        self,
        items: List[Dict[str, Any]],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        texts = [str(item.get("text") or "") for item in items]
        return await self.translate_batch(texts, source_lang, target_lang)


class AioHttpTranslationService(TranslationService):
    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=180)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session


def _build_translation_messages(payload: str, source_lang: str, target_lang: str) -> List[Dict[str, str]]:
    source_label = _language_name(source_lang)
    target_label = _language_name(target_lang)
    return [
        {
            "role": "system",
            "content": (
                f"You are a professional, neutral translator.\n\n"
                f"Translation guidelines:\n"
                f"1. Translate all translatable content from {source_label} to {target_label} naturally and fluently.\n"
                f"2. Do not leave source-language phrases untranslated unless they are proper nouns, brand names, product names, abbreviations, citations, or technical terms commonly used in {target_label}.\n"
                f"3. Maintain the original tone and style.\n"
                f"4. Preserve layout markers such as line breaks, bullets, numbering, emoji, and leading symbols.\n"
                f"5. Do not add explanations, notes, glosses, or parenthetical original terms unless they already exist in the source text.\n"
                f"6. Do not add new line breaks inside a paragraph; preserve only the source paragraph breaks.\n"
                f"7. Return only the translated text unless the user explicitly asks for JSON."
            ),
        },
        {"role": "user", "content": payload},
    ]


def _extract_json_array(raw_response: str) -> Any:
    text = raw_response.strip()
    fenced_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced_match:
        text = fenced_match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def _build_structured_batch_payload(items: List[Dict[str, Any]]) -> str:
    serializable_items = []
    for index, item in enumerate(items):
        serializable_items.append({
            "id": index,
            "text": str(item.get("text") or ""),
            "role": str(item.get("role") or "body"),
            "lineCount": int(item.get("lineCount") or 1),
            "leadingMarker": str(item.get("leadingMarker") or ""),
            "endsWithSentencePunctuation": bool(item.get("endsWithSentencePunctuation")),
        })
    return json.dumps(serializable_items, ensure_ascii=False)


def _build_structured_batch_messages(
    items: List[Dict[str, Any]],
    source_lang: str,
    target_lang: str,
) -> List[Dict[str, str]]:
    payload = _build_structured_batch_payload(items)
    return _build_translation_messages(
        (
            "Translate every item in the JSON array independently.\n"
            "Return JSON only in exactly this shape: "
            '[{"id":0,"translatedText":"..."}, ...].\n'
            "Do not omit any item. Keep ids unchanged.\n"
            "Do not merge adjacent items, split one item into multiple items, or move content between items.\n"
            "Preserve each item's role: headings should remain concise headings; body text should remain one paragraph unless the source contains explicit paragraph breaks.\n"
            "Preserve leadingMarker exactly at the start of translatedText when it is non-empty.\n"
            "Preserve placeholder tokens like [[REF0]] exactly; do not translate, remove, reorder, or alter them.\n"
            "Preserve numeric expressions, comparison operators, percentages, ranges, bullets, numbering, citations, figure/table labels, and symbols exactly in meaning and local order.\n"
            "Do not add explanations, notes, glosses, markdown, or extra line breaks.\n"
            f"Input JSON:\n{payload}"
        ),
        source_lang,
        target_lang,
    )


def _parse_batch_translations(raw_response: str, expected_count: int) -> List[str]:
    try:
        parsed = _extract_json_array(raw_response)
    except json.JSONDecodeError as exc:
        raise Exception(f"Batch translation returned invalid JSON: {exc}") from exc

    if not isinstance(parsed, list):
        raise Exception("Batch translation response must be a JSON array")

    translations_by_id: Dict[int, str] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        translated_text = item.get("translatedText")
        if isinstance(item_id, int) and isinstance(translated_text, str):
            translations_by_id[item_id] = translated_text.strip()

    if len(translations_by_id) != expected_count:
        raise Exception("Batch translation response is missing items")

    return [translations_by_id[index] for index in range(expected_count)]


class DeepLService(AioHttpTranslationService):
    def __init__(self) -> None:
        super().__init__()
        self.api_key = os.getenv("DEEPL_API_KEY")
        self.base_url = "https://api-free.deepl.com/v2/translate"

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not self.api_key:
            raise ValueError("DeepL API key not configured")

        session = await self._get_session()
        data = {
            "auth_key": self.api_key,
            "text": text,
            "source_lang": source_lang.upper(),
            "target_lang": target_lang.upper(),
        }
        async with session.post(self.base_url, data=data) as response:
            if response.status != 200:
                raise Exception(f"DeepL API error: {response.status}")
            result = await response.json()
            return result["translations"][0]["text"]

    def get_supported_languages(self) -> List[str]:
        return list(SUPPORTED_LANGUAGE_CODES)


class GoogleTranslateService(AioHttpTranslationService):
    def __init__(self) -> None:
        super().__init__()
        self.api_key = os.getenv("GOOGLE_TRANSLATE_API_KEY")
        self.base_url = "https://translation.googleapis.com/language/translate/v2"

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not self.api_key:
            raise ValueError("Google Translate API key not configured")

        session = await self._get_session()
        params = {
            "key": self.api_key,
            "q": text,
            "source": source_lang,
            "target": target_lang,
        }
        async with session.get(self.base_url, params=params) as response:
            if response.status != 200:
                raise Exception(f"Google API error: {response.status}")
            result = await response.json()
            return result["data"]["translations"][0]["translatedText"]

    def get_supported_languages(self) -> List[str]:
        return list(SUPPORTED_LANGUAGE_CODES)


class OpenAIService(AioHttpTranslationService):
    def __init__(self) -> None:
        super().__init__()
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = "https://api.openai.com/v1/chat/completions"

    async def _request_completion(self, messages: List[Dict[str, str]]) -> str:
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        data = {
            "model": "gpt-4o",
            "messages": messages,
            "temperature": 0.3,
        }
        async with session.post(self.base_url, headers=headers, json=data) as response:
            if response.status != 200:
                raise Exception(f"OpenAI API error: {response.status}")
            result = await response.json()
            return result["choices"][0]["message"]["content"].strip()

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        return await self._request_completion(_build_translation_messages(text, source_lang, target_lang))

    async def translate_structured_batch(
        self,
        items: List[Dict[str, Any]],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        if not items:
            return []
        raw_response = await self._request_completion(
            _build_structured_batch_messages(items, source_lang, target_lang)
        )
        return _parse_batch_translations(raw_response, len(items))

    async def translate_batch(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        items = [{"text": text, "role": "body"} for text in texts]
        return await self.translate_structured_batch(items, source_lang, target_lang)

    def get_supported_languages(self) -> List[str]:
        return list(SUPPORTED_LANGUAGE_CODES)


class OfoxAIService(AioHttpTranslationService):
    def __init__(self) -> None:
        super().__init__()

    def _get_config(self, model_override: Optional[str] = None) -> Tuple[str, str, str]:
        api_key = os.getenv("OFOXAI_API_KEY")
        base_url = os.getenv("OFOXAI_BASE_URL", "https://api.ofox.ai/v1").rstrip("/")
        model = model_override or os.getenv("OFOXAI_SUBSCRIPTION_MODEL") or os.getenv("OFOXAI_MODEL", "gpt-5.4-mini")
        if not api_key or api_key == "your_ofoxai_api_key_here":
            raise ValueError("OfoxAI API key not configured. Please set OFOXAI_API_KEY in .env file")
        return api_key, base_url, model

    async def _request_completion(
        self,
        messages: List[Dict[str, str]],
        *,
        api_key: str,
        base_url: str,
        model: str,
    ) -> str:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
        }

        async with session.post(f"{base_url}/chat/completions", headers=headers, json=data) as response:
            if response.status != 200:
                error_text = await response.text()
                safe_print(f"[DEBUG] API error {response.status}: {error_text}")
                raise Exception(f"OfoxAI API error: {response.status} - {error_text}")
            result = await response.json()
            translated_text = result["choices"][0]["message"]["content"].strip()
            safe_translated = translated_text.encode("utf-8", errors="ignore").decode("utf-8")
            safe_print(
                f"[DEBUG] OfoxAIService.translate success: result_length={len(translated_text)}, "
                f"first_50_chars={safe_translated[:50]}"
            )
            return translated_text

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        api_key, base_url, model = self._get_config()
        safe_print(
            f"[DEBUG] OfoxAIService.translate called: text_length={len(text)}, "
            f"source={source_lang}, target={target_lang}"
        )
        messages = _build_translation_messages(text, source_lang, target_lang)
        return await self._request_completion(messages, api_key=api_key, base_url=base_url, model=model)

    async def translate_batch(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        items = [{"text": text, "role": "body"} for text in texts]
        return await self.translate_structured_batch(items, source_lang, target_lang)

    async def translate_structured_batch(
        self,
        items: List[Dict[str, Any]],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        if not items:
            return []

        api_key, base_url, model = self._get_config()
        return await self._translate_structured_batch_with_config(
            items,
            source_lang,
            target_lang,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )

    async def translate_structured_batch_with_model(
        self,
        items: List[Dict[str, Any]],
        source_lang: str,
        target_lang: str,
        *,
        model: str,
    ) -> List[str]:
        if not items:
            return []

        api_key, base_url, selected_model = self._get_config(model)
        return await self._translate_structured_batch_with_config(
            items,
            source_lang,
            target_lang,
            api_key=api_key,
            base_url=base_url,
            model=selected_model,
        )

    async def _translate_structured_batch_with_config(
        self,
        items: List[Dict[str, Any]],
        source_lang: str,
        target_lang: str,
        *,
        api_key: str,
        base_url: str,
        model: str,
    ) -> List[str]:
        messages = _build_structured_batch_messages(items, source_lang, target_lang)
        raw_response = await self._request_completion(
            messages,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        return _parse_batch_translations(raw_response, len(items))

    def get_supported_languages(self) -> List[str]:
        return list(SUPPORTED_LANGUAGE_CODES)


def get_translation_model_for_plan(plan: Optional[str]) -> str:
    normalized_plan = (plan or "free").strip().lower()
    if normalized_plan == "free":
        return os.getenv("OFOXAI_FREE_MODEL", "gpt-5.4-nano")
    return os.getenv("OFOXAI_SUBSCRIPTION_MODEL", "gpt-5.4-mini")


class MockTranslationService(TranslationService):
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if source_lang == target_lang:
            return text

        return f"[{target_lang}: {text}]"

    def get_supported_languages(self) -> List[str]:
        return list(SUPPORTED_LANGUAGE_CODES)


class TranslationServiceFactory:
    _services: Dict[str, TranslationService] = {}

    @classmethod
    def register(cls, name: str, service: TranslationService) -> None:
        cls._services[name] = service

    @classmethod
    def get(cls, name: str = "mock") -> TranslationService:
        return cls._services.get(name) or MockTranslationService()


TranslationServiceFactory.register("mock", MockTranslationService())
TranslationServiceFactory.register("deepl", DeepLService())
TranslationServiceFactory.register("google", GoogleTranslateService())
TranslationServiceFactory.register("openai", OpenAIService())
TranslationServiceFactory.register("ofoxai", OfoxAIService())
